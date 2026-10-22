"""Integration test for the raw-socket SOCKS4 checker.

Runs a local HTTP judge and a local SOCKS4 relay server, then checks a
proxy pointing at the relay — no external network involved.
"""

from __future__ import annotations

import asyncio
import socket

import pytest

from proxy_tester import checker
from proxy_tester.checker import check_proxy
from proxy_tester.parser import parse_line

JUDGE_BODY = b"203.0.113.99"


async def _handle_judge(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    await reader.readuntil(b"\r\n\r\n")
    head = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: text/plain\r\n"
        + f"Content-Length: {len(JUDGE_BODY)}\r\n".encode()
        + b"Connection: close\r\n\r\n"
    )
    writer.write(head + JUDGE_BODY)
    await writer.drain()
    writer.close()


async def _handle_socks4(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Minimal SOCKS4/4A CONNECT relay."""
    header = await reader.readexactly(8)
    version, command = header[0], header[1]
    port = int.from_bytes(header[2:4], "big")
    ip_bytes = header[4:8]

    userid = await reader.readuntil(b"\x00")
    del userid
    if ip_bytes[:3] == b"\x00\x00\x00" and ip_bytes[3] != 0:  # SOCKS4A
        hostname = (await reader.readuntil(b"\x00"))[:-1].decode()
        dest_host = hostname
    else:
        dest_host = socket.inet_ntoa(ip_bytes)
    del version, command

    try:
        remote_reader, remote_writer = await asyncio.open_connection(dest_host, port)
    except OSError:
        writer.write(b"\x00\x5b\x00\x00\x00\x00\x00\x00")  # request rejected (0x5B)
        await writer.drain()
        writer.close()
        return

    writer.write(b"\x00\x5a" + header[2:4] + header[4:8])  # request granted
    await writer.drain()

    async def pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter):
        try:
            while chunk := await src.read(4096):
                dst.write(chunk)
                await dst.drain()
        except OSError:
            pass
        finally:
            try:
                dst.close()
            except OSError:
                pass

    await asyncio.gather(pump(reader, remote_writer), pump(remote_reader, writer))


@pytest.fixture
async def servers():
    judge_server = await asyncio.start_server(_handle_judge, "127.0.0.1", 0)
    socks_server = await asyncio.start_server(_handle_socks4, "127.0.0.1", 0)
    judge_port = judge_server.sockets[0].getsockname()[1]
    socks_port = socks_server.sockets[0].getsockname()[1]
    async with judge_server, socks_server:
        yield f"http://127.0.0.1:{judge_port}/ip", socks_port


@pytest.fixture(autouse=True)
def clear_dns_cache():
    checker._resolve_cache.clear()
    yield
    checker._resolve_cache.clear()


async def test_socks4_working(servers):
    judge, socks_port = servers
    proxy = parse_line(f"socks4://127.0.0.1:{socks_port}")
    result = await check_proxy(proxy, judge, timeout=5)
    assert result.working, result.error
    assert result.exit_ip == JUDGE_BODY.decode()
    assert result.latency_ms is not None and result.latency_ms > 0


async def test_socks4a_fallback_when_dns_unavailable(servers):
    """When the judge host cannot be resolved locally, SOCKS4A is used."""
    judge, socks_port = servers
    host = "localhost"  # relay resolves it too; checker must not resolve it itself
    checker._resolve_cache[host] = None  # force resolution "failure"
    judge_url = judge.replace("127.0.0.1", "localhost")
    proxy = parse_line(f"socks4://127.0.0.1:{socks_port}")
    result = await check_proxy(proxy, judge_url, timeout=5)
    assert result.working, result.error
    assert result.exit_ip == JUDGE_BODY.decode()


async def test_socks4_rejected(servers):
    """A relay that cannot reach the judge reports a rejection, not a crash."""
    judge, socks_port = servers
    closed_port = _free_port()
    proxy = parse_line(f"socks4://127.0.0.1:{socks_port}")
    result = await check_proxy(proxy, f"http://127.0.0.1:{closed_port}/ip", timeout=5)
    assert not result.working
    assert result.error == "network error: socks4 rejected: request_rejected_or_failed"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
