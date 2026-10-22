from proxy_tester.parser import parse_file, parse_line


class TestParseLine:
    def test_scheme_url(self):
        proxy = parse_line("socks5://45.74.31.40:6772")
        assert proxy is not None
        assert (proxy.protocol, proxy.host, proxy.port) == ("socks5", "45.74.31.40", 6772)
        assert proxy.url == "socks5://45.74.31.40:6772"

    def test_scheme_uppercase(self):
        assert parse_line("SOCKS4://1.2.3.4:1080").protocol == "socks4"

    def test_bare_host_port_uses_default(self):
        assert parse_line("1.2.3.4:8080").protocol == "http"
        assert parse_line("1.2.3.4:8080", "socks5").protocol == "socks5"

    def test_auth(self):
        proxy = parse_line("http://user:pass@1.2.3.4:3128")
        assert proxy.url == "http://user:pass@1.2.3.4:3128"

    def test_username_only_auth(self):
        proxy = parse_line("1.2.3.4:3128", "socks5")
        assert proxy.username is None

    def test_hostname(self):
        assert parse_line("proxy.example.com:3128").host == "proxy.example.com"

    def test_ipv6_bracketed(self):
        assert parse_line("socks5://[2001:db8::1]:1080").host == "2001:db8::1"

    def test_comment_and_blank(self):
        assert parse_line("") is None
        assert parse_line("   ") is None
        assert parse_line("# comment") is None

    def test_invalid(self):
        assert parse_line("not a proxy") is None
        assert parse_line("1.2.3.4") is None          # no port
        assert parse_line("1.2.3.4:0") is None         # port out of range
        assert parse_line("1.2.3.4:70000") is None
        assert parse_line("1.2.3.4:abc") is None
        assert parse_line("ftp://1.2.3.4:21") is None  # unsupported scheme
        assert parse_line("bad_host!:8080") is None


class TestParseFile:
    def test_mixed_file(self, tmp_path):
        path = tmp_path / "list.txt"
        path.write_text(
            "socks5://1.2.3.4:1080\n"
            "\n"
            "# comment\n"
            "1.2.3.4:8080\n"
            "socks5://1.2.3.4:1080\n"   # duplicate
            "garbage line\n",
            encoding="utf-8",
        )
        proxies, skipped = parse_file(str(path))
        assert [p.url for p in proxies] == [
            "socks5://1.2.3.4:1080",
            "http://1.2.3.4:8080",
        ]
        assert skipped == 2  # duplicate + garbage
