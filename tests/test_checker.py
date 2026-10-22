import pytest

from proxy_tester.checker import _error_summary, extract_ip, parse_judge


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
