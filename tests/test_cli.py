"""CLI argument validation and input-file error handling."""

import pytest

from proxy_tester.cli import build_parser, main


class TestArgValidation:
    @pytest.mark.parametrize("value", ["0", "-1", "-5.5", "nan", "inf", "abc"])
    def test_bad_timeout_exits_2(self, value):
        with pytest.raises(SystemExit) as exc:
            build_parser().parse_args(["test", "proxies.txt", "--timeout", value])
        assert exc.value.code == 2

    @pytest.mark.parametrize("value", ["0", "-3", "1.5", "abc"])
    def test_bad_concurrency_exits_2(self, value):
        with pytest.raises(SystemExit) as exc:
            build_parser().parse_args(["test", "proxies.txt", "--concurrency", value])
        assert exc.value.code == 2

    @pytest.mark.parametrize("value", ["0", "-1"])
    def test_bad_limit_exits_2(self, value):
        with pytest.raises(SystemExit) as exc:
            build_parser().parse_args(["test", "proxies.txt", "--limit", value])
        assert exc.value.code == 2

    def test_valid_values_accepted(self):
        args = build_parser().parse_args(
            ["test", "proxies.txt", "--timeout", "0.5", "--concurrency", "1", "--limit", "3"]
        )
        assert (args.timeout, args.concurrency, args.limit) == (0.5, 1, 3)


class TestInputFileErrors:
    def test_missing_file_returns_2(self, tmp_path, capsys):
        assert main(["test", str(tmp_path / "nope.txt")]) == 2
        assert "Cannot read proxy file" in capsys.readouterr().out

    def test_directory_input_returns_2(self, tmp_path, capsys):
        assert main(["test", str(tmp_path)]) == 2
        assert "Cannot read proxy file" in capsys.readouterr().out
