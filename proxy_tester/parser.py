"""Parsing of proxy list files into Proxy objects."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

SUPPORTED_PROTOCOLS = ("http", "https", "socks4", "socks5")

_SCHEME_RE = re.compile(r"^(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*)://")
_USERINFO_RE = re.compile(r"^(?P<user>[^@/:]+)(?::(?P<password>[^@/]*))?@")
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?"
    r"(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$"
)


@dataclass(frozen=True)
class Proxy:
    protocol: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None

    @property
    def url(self) -> str:
        auth = ""
        if self.username is not None:
            auth = f"{self.username}:{self.password or ''}@"
        return f"{self.protocol}://{auth}{self.host}:{self.port}"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.url


def _valid_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return bool(_HOSTNAME_RE.match(host))


def parse_line(line: str, default_protocol: str = "http") -> Proxy | None:
    """Parse one line of a proxy list.

    Accepted forms::

        protocol://ip:port
        protocol://user:pass@ip:port
        user:pass@ip:port          (uses default_protocol)
        ip:port                    (uses default_protocol)
        [ipv6]:port

    Returns None for blank lines, comments and malformed entries.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if default_protocol not in SUPPORTED_PROTOCOLS:
        raise ValueError(f"unsupported protocol: {default_protocol}")

    protocol = default_protocol
    if (m := _SCHEME_RE.match(line)) is not None:
        protocol = m.group("scheme").lower()
        if protocol not in SUPPORTED_PROTOCOLS:
            return None
        line = line[m.end():]

    username: str | None = None
    password: str | None = None
    if (m := _USERINFO_RE.match(line)) is not None:
        username, password = m.group("user"), m.group("password")
        line = line[m.end():]

    # IPv6 literals may be bracketed.
    if line.startswith("["):
        end = line.find("]")
        if end == -1:
            return None
        host, rest = line[1:end], line[end + 1:]
        if not rest.startswith(":"):
            return None
        port_str = rest[1:]
    else:
        host, sep, port_str = line.rpartition(":")
        if not sep or not host:
            return None

    if not port_str.isdigit():
        return None
    port = int(port_str)
    if not 1 <= port <= 65535:
        return None
    if not _valid_host(host):
        return None

    return Proxy(
        protocol=protocol,
        host=host,
        port=port,
        username=username,
        password=password,
    )


def parse_file(path: str, default_protocol: str = "http") -> tuple[list[Proxy], int]:
    """Parse a proxy list file.

    Returns (proxies, skipped) where duplicates are removed and *skipped*
    counts blank/invalid/duplicate lines.
    """
    proxies: list[Proxy] = []
    seen: set[str] = set()
    skipped = 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            proxy = parse_line(line, default_protocol)
            if proxy is None:
                if line.strip() and not line.strip().startswith("#"):
                    skipped += 1
                continue
            if proxy.url in seen:
                skipped += 1
                continue
            seen.add(proxy.url)
            proxies.append(proxy)
    return proxies, skipped
