from rich.console import Console

from proxy_tester.checker import ProxyResult, extract_ip
from proxy_tester.parser import Proxy
from proxy_tester.report import (
    final_table,
    result_line,
    summary_text,
    write_json,
    write_working,
)


def _result(**kwargs) -> ProxyResult:
    defaults = dict(proxy=Proxy("socks5", "1.2.3.4", 1080))
    defaults.update(kwargs)
    return ProxyResult(**defaults)


class TestExtractIp:
    def test_plain_body(self):
        assert extract_ip("203.0.113.7") == "203.0.113.7"

    def test_plain_body_with_noise(self):
        assert extract_ip("Your IP: 198.51.100.22\n") == "198.51.100.22"

    def test_json_ipify(self):
        assert extract_ip('{"ip": "203.0.113.9"}') == "203.0.113.9"

    def test_json_httpbin_origin_list(self):
        assert extract_ip('{"origin": "203.0.113.3, 10.0.0.1"}') == "203.0.113.3"

    def test_json_no_ip_key(self):
        assert extract_ip('{"foo": "bar"}') is None

    def test_garbage(self):
        assert extract_ip("hello world") is None


class TestReport:
    def test_write_working_only_includes_working(self, tmp_path):
        results = [
            _result(working=True, latency_ms=120.0, exit_ip="9.9.9.9"),
            _result(working=False, error="connect timeout"),
        ]
        path = tmp_path / "working.txt"
        assert write_working(results, str(path)) == 1
        assert path.read_text() == "socks5://1.2.3.4:1080\n"

    def test_write_json_structure(self, tmp_path):
        results = [_result(working=True, latency_ms=120.0, exit_ip="9.9.9.9", anonymous=True, country="India")]
        path = tmp_path / "results.json"
        write_json(results, str(path), judge="https://exampleJudge")
        import json

        payload = json.loads(path.read_text())
        assert payload["counts"] == {"total": 1, "working": 1}
        assert payload["judge"] == "https://exampleJudge"
        entry = payload["results"][0]
        assert entry["proxy"] == "socks5://1.2.3.4:1080"
        assert entry["country"] == "India"

    def test_final_table_sorts_by_latency(self):
        slow = _result(working=True, latency_ms=5000.0)
        fast = _result(working=True, latency_ms=100.0)
        table = final_table([slow, fast], sort="latency")
        console = Console(width=160)
        with console.capture() as capture:
            console.print(table)
        rendered = capture.get()
        assert rendered.index("100 ms") < rendered.index("5000 ms")

    def test_result_line_working(self):
        result = _result(working=True, latency_ms=1027.4, exit_ip="9.9.9.9", anonymous=True)
        plain = result_line(result).plain
        assert "✔" in plain
        assert "socks5://1.2.3.4:1080" in plain
        assert "1027 ms" in plain
        assert "exit 9.9.9.9" in plain
        assert "anon" in plain

    def test_result_line_failed_shows_error(self):
        result = _result(working=False, error="connect timeout")
        plain = result_line(result).plain
        assert "✘" in plain
        assert "connect timeout" in plain
        assert "exit" not in plain

    def test_final_table_shows_as_name_next_to_exit_ip(self):
        result = _result(
            working=True,
            latency_ms=100.0,
            exit_ip="9.9.9.9",
            as_name="AS22773 Cox Communications Inc.",
        )
        table = final_table([result])
        console = Console(width=160)
        with console.capture() as capture:
            console.print(table)
        rendered = capture.get()
        assert "9.9.9.9" in rendered
        assert "AS22773 Cox Communications Inc." in rendered

    def test_summary_counts(self):
        text = summary_text(
            [
                _result(working=True, latency_ms=100.0, anonymous=True),
                _result(working=False),
            ]
        )
        plain = text.plain
        assert "tested 2" in plain and "working 1" in plain and "failed 1" in plain
