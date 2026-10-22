"""Async proxy checking engine."""

from __future__ import annotations

import asyncio
import functools
import ipaddress
import json
import re
import socket
import ssl
import time
from dataclasses import asdict, dataclass
from typing import Awaitable, Callable
from urllib.parse import urlsplit

import httpx
from socksio import socks4

from . import __version__
from .parser import Proxy

_IP_RE = re.compile(
    r"\d{1,3}(?:\.\d{1,3}){3}|(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}"
)

# Called with each finished result, in completion order.
OnResult = Callable[["ProxyResult"], Awaitable[None]] | None


@dataclass
class ProxyResult:
    proxy: Proxy
    working: bool = False
    latency_ms: float | None = None
    exit_ip: str | None = None
    anonymous: bool | None = None
    country: str | None = None
    country_code: str | None = None
    as_name: str | None = None
    as_registry: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self) | {"proxy": self.proxy.url}


def _looks_like_ip(value: str) -> str | None:
    value = value.strip()
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def extract_ip(text: str) -> str | None:
    """Extract the client IP from a judge response.

    Understands plain-IP bodies (``api.iplocate.io/ip``) and JSON bodies with
    an ``ip``/``origin``/``query`` key (ipify, httpbin, ip-api, ...).
    """
    text = text.strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        data = None
    if isinstance(data, dict):
        for key in ("origin", "ip", "query", "yourIp", "YourFuckingIPAddress"):
            value = data.get(key)
            if isinstance(value, str):
                # httpbin "origin" can be "1.2.3.4, 5.6.7.8"
                candidate = value.split(",")[0]
                if (ip := _looks_like_ip(candidate)) is not None:
                    return ip
        return None
    for candidate in _IP_RE.findall(text):
        ip = _looks_like_ip(candidate)
        if ip is not None:
            return ip
    return None


def _error_summary(exc: Exception) -> str:
    label = {
        httpx.ConnectTimeout: "connect timeout",
        httpx.ConnectError: "connect error",
        httpx.ReadTimeout: "read timeout",
        httpx.WriteTimeout: "write timeout",
        httpx.PoolTimeout: "pool timeout",
        httpx.ProxyError: "proxy error",
        asyncio.TimeoutError: "timeout",
        ConnectionError: "network error",
        ConnectionRefusedError: "connect error (refused)",
        ssl.SSLError: "tls error",
        OSError: "network error",
    }.get(type(exc), type(exc).__name__)
    detail = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    if detail and detail.lower() not in label.lower():
        return f"{label}: {detail[:60]}"
    return label


@functools.lru_cache(maxsize=16)
def parse_judge(judge: str) -> tuple[str, str, int, str, str]:
    """Split a judge URL into (scheme, host, port, path, host_header)."""
    parts = urlsplit(judge if "://" in judge else f"http://{judge}")
    scheme = parts.scheme or "http"
    if scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"invalid judge URL: {judge!r}")
    port = parts.port or (443 if scheme == "https" else 80)
    path = parts.path or "/"
    if parts.query:
        path += f"?{parts.query}"
    host_header = parts.hostname if port in (80, 443) else f"{parts.hostname}:{port}"
    return scheme, parts.hostname, port, path, host_header


_resolve_cache: dict[str, str | None] = {}


async def _resolve_host(host: str) -> str | None:
    """Resolve a hostname to an IPv4 address (cached per run)."""
    if host in _resolve_cache:
        return _resolve_cache[host]
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        infos = []
    resolved: str | None = None
    for info in infos:
        ip = info[4][0]
        try:
            if ipaddress.ip_address(ip).version == 4:
                resolved = ip
                break
        except ValueError:
            continue
    if resolved is None and infos:
        resolved = infos[0][4][0]
    _resolve_cache[host] = resolved
    return resolved


def _tls_context() -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


async def check_socks4_proxy(
    proxy: Proxy,
    judge: str,
    timeout: float,
) -> ProxyResult:
    """Test a SOCKS4 proxy with a raw socket handshake (httpx only does SOCKS5).

    The judge host is resolved locally and sent as a plain SOCKS4 request for
    maximum server compatibility; if local resolution fails we fall back to a
    SOCKS4A request and let the proxy resolve it.
    """
    scheme, host, port, path, host_header = parse_judge(judge)
    result = ProxyResult(proxy=proxy)
    start = time.perf_counter()

    def _finish(**kwargs) -> ProxyResult:
        result.latency_ms = (time.perf_counter() - start) * 1000
        for key, value in kwargs.items():
            setattr(result, key, value)
        return result

    try:
        async with asyncio.timeout(timeout):
            reader, writer = await asyncio.open_connection(proxy.host, proxy.port)
            try:
                # Non-empty user id: socksio's `user_id or self.user_id` logic
                # treats b"" as unset, and SOCKS4 servers ignore the value.
                connection = socks4.SOCKS4Connection(user_id=b"anonymous")
                resolved = await _resolve_host(host)
                if resolved is not None:
                    request = socks4.SOCKS4Request.from_address(
                        socks4.SOCKS4Command.CONNECT, (resolved, port)
                    )
                else:
                    request = socks4.SOCKS4ARequest.from_address(
                        socks4.SOCKS4Command.CONNECT, (host, port)
                    )
                connection.send(request)
                writer.write(connection.data_to_send())
                reply = connection.receive_data(await reader.readexactly(8))
                if reply.reply_code != socks4.SOCKS4ReplyCode.REQUEST_GRANTED:
                    raise ConnectionError(
                        f"socks4 rejected: {getattr(reply.reply_code, 'name', reply.reply_code).lower()}"
                    )

                # Python 3.13 start_tls() upgrades the transport in place
                # (returns None), so keep using the same reader/writer.
                if scheme == "https":
                    await writer.start_tls(_tls_context(), server_hostname=host)

                writer.write(
                    f"GET {path} HTTP/1.1\r\n"
                    f"Host: {host_header}\r\n"
                    f"User-Agent: proxy-tester/{__version__}\r\n"
                    f"Accept: */*\r\n"
                    f"Connection: close\r\n\r\n".encode()
                )
                await writer.drain()
                data = await reader.read(-1)
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - report any failure as a dead proxy
        return _finish(error=_error_summary(exc))

    head, _, body = data.partition(b"\r\n\r\n")
    try:
        status = int(head.split(b"\r\n", 1)[0].split()[1])
    except (IndexError, ValueError):
        return _finish(error="malformed judge response")
    if not 200 <= status < 300:
        return _finish(error=f"HTTP {status}")
    exit_ip = extract_ip(body.decode("utf-8", "replace"))
    if exit_ip is None:
        return _finish(error="no IP in judge response")
    return _finish(working=True, exit_ip=exit_ip)


async def check_proxy(
    proxy: Proxy,
    judge: str,
    timeout: float,
) -> ProxyResult:
    """Fetch the judge URL through one proxy and measure latency."""
    if proxy.protocol == "socks4":
        return await check_socks4_proxy(proxy, judge, timeout)

    result = ProxyResult(proxy=proxy)
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            proxy=proxy.url,
            timeout=timeout,
            verify=False,  # free proxies often intercept TLS; we only test reachability
            trust_env=False,
            follow_redirects=True,
        ) as client:
            response = await client.get(judge)
            result.latency_ms = (time.perf_counter() - start) * 1000
            if 200 <= response.status_code < 300:
                result.exit_ip = extract_ip(response.text)
                if result.exit_ip is None:
                    result.error = "no IP in judge response"
                else:
                    result.working = True
            else:
                result.error = f"HTTP {response.status_code}"
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - report any failure as a dead proxy
        result.latency_ms = (time.perf_counter() - start) * 1000
        result.error = _error_summary(exc)
    return result


async def fetch_real_ip(judge: str, timeout: float = 10.0) -> str | None:
    """Fetch our direct (non-proxied) IP from the judge."""
    try:
        async with httpx.AsyncClient(
            timeout=timeout, verify=False, trust_env=False, follow_redirects=True
        ) as client:
            response = await client.get(judge)
            if 200 <= response.status_code < 300:
                return extract_ip(response.text)
    except Exception:  # noqa: BLE001 - best effort
        return None
    return None


async def run_checks(
    proxies: list[Proxy],
    judge: str,
    timeout: float,
    concurrency: int,
    on_result: OnResult = None,
    real_ip: str | None = None,
) -> list[ProxyResult]:
    """Check all proxies concurrently, in completion order."""
    semaphore = asyncio.Semaphore(concurrency)

    async def _one(proxy: Proxy) -> ProxyResult:
        async with semaphore:
            result = await check_proxy(proxy, judge, timeout)
        if real_ip is not None and result.exit_ip is not None:
            result.anonymous = result.exit_ip != real_ip
        if on_result is not None:
            await on_result(result)
        return result

    tasks = [asyncio.create_task(_one(proxy)) for proxy in proxies]
    try:
        return list(await asyncio.gather(*tasks))
    except KeyboardInterrupt:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
