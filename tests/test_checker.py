import asyncio

import pytest

from proxy_tester.checker import (
    ProxyResult,
    _error_summary,
    extract_ip,
    parse_judge,
    run_checks,
)
from proxy_tester.parser import Proxy


class TestParseJudge:
    def test_https_default_port(self):
        scheme, host, port, path, header = parse_judge("https://api.iplocate.io/ip")
        assert (scheme, host, port, path, header) == (
            "https", "api.iplocate.io", 443, "/ip", "api.iplocate.io",
        )

    def test_http_with_port_and_query(self):
        scheme, host, port, path, header = parse_judge("http://example.com:8080/judge?a=1")
        assert (scheme, port, path, header) == ("http", 8080, "/judge?a=1", "example.com:8080")

    def test_invalid(self):
        with pytest.raises(ValueError):
            parse_judge("ftp://example.com/x")


class TestErrorSummary:
    def test_known_exception(self):
        import httpx

        assert _error_summary(httpx.ConnectTimeout("timed out")) == "connect timeout: timed out"

    def test_detail_duplicated_in_label_is_skipped(self):
        import httpx

        assert _error_summary(httpx.ReadTimeout("Read timeout")) == "read timeout"

    def test_unknown_exception_uses_class_name(self):
        assert _error_summary(RuntimeError("boom")) == "RuntimeError: boom"


class TestExtractIpSocksHelpers:
    def test_ipv6_plain(self):
        assert extract_ip("2604:a880:800:10::b1:1001") == "2604:a880:800:10::b1:1001"


class TestRunChecksBackstop:
    """The 2x-timeout backstop must free the run from checks that hang
    outside the request timeout (e.g. in client/transport teardown)."""

    async def test_hanging_check_is_cut_off(self, monkeypatch):
        proxy = Proxy(protocol="http", host="1.2.3.4", port=8080)

        async def hang(p, judge, timeout):
            await asyncio.sleep(3600)

        monkeypatch.setattr("proxy_tester.checker.check_proxy", hang)
        results = await run_checks([proxy], judge="http://judge", timeout=0.05, concurrency=1)
        assert len(results) == 1
        assert results[0].working is False
        assert results[0].error == "timeout"

    async def test_hanging_on_result_callback_is_not_bounded(self, monkeypatch):
        """on_result runs outside the backstop by design (it is local reporting)."""
        proxy = Proxy(protocol="http", host="1.2.3.4", port=8080)
        seen = []

        async def ok(p, judge, timeout):
            return ProxyResult(proxy=p, working=True, exit_ip="5.6.7.8")

        async def on_result(result):
            seen.append(result)

        monkeypatch.setattr("proxy_tester.checker.check_proxy", ok)
        results = await run_checks(
            [proxy], judge="http://judge", timeout=0.05, concurrency=1,
            on_result=on_result, real_ip="9.9.9.9",
        )
        assert results[0].working is True
        assert results[0].anonymous is True
        assert seen == results

    async def test_mixed_hanging_and_ok_checks_complete(self, monkeypatch):
        proxies = [Proxy(protocol="http", host=f"1.2.3.{i}", port=8080) for i in range(1, 4)]

        async def mixed(p, judge, timeout):
            if p.host.endswith(".1"):
                await asyncio.sleep(3600)  # hang beyond any internal timeout
            return ProxyResult(proxy=p, working=True, exit_ip="5.6.7.8")

        monkeypatch.setattr("proxy_tester.checker.check_proxy", mixed)
        results = await run_checks(proxies, judge="http://judge", timeout=0.05, concurrency=3)
        by_host = {r.proxy.host: r for r in results}
        assert by_host["1.2.3.1"].error == "timeout"
        assert by_host["1.2.3.1"].working is False
        assert by_host["1.2.3.2"].working is True
        assert by_host["1.2.3.3"].working is True


class TestRunChecksValidation:
    """run_checks must reject values that would deadlock or fail every check."""

    async def test_zero_concurrency_raises(self):
        proxy = Proxy(protocol="http", host="1.2.3.4", port=8080)
        with pytest.raises(ValueError, match="concurrency"):
            await run_checks([proxy], judge="http://j", timeout=1.0, concurrency=0)

    async def test_non_positive_timeout_raises(self):
        proxy = Proxy(protocol="http", host="1.2.3.4", port=8080)
        with pytest.raises(ValueError, match="timeout"):
            await run_checks([proxy], judge="http://j", timeout=0, concurrency=1)
