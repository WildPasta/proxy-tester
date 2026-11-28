# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-11-28

### Fixed

- CLI: `--timeout`, `--concurrency` and `--limit` now reject zero, negative,
  non-finite or non-numeric values with a usage error (exit 2). Previously
  `--concurrency 0` could hang the whole run and `--limit 0` silently
  disabled the limit.
- CLI: a missing or unreadable proxy list file now prints a friendly error
  message and exits with code 2 instead of dumping a Python traceback.
- `run_checks()` raises `ValueError` when called with `concurrency < 1` or
  `timeout <= 0`, protecting library callers from the same deadlock.

### Changed

- Exit code `2` now signals input/usage errors, distinct from exit `1`
  (no working proxies) and `0` (at least one working proxy). Documented in
  the README.

### CI

- Dependabot branches are deleted automatically after an auto-merge.

## [1.0.0] - 2026-10-23

Initial release: async CLI tool that tests HTTP/HTTPS/SOCKS4/SOCKS5 proxies
from a list file — working status, latency, anonymity check (exit IP vs.
direct IP) and exit-country geolocation, with streaming per-proxy results,
a rich final table, and `working.txt` / `results.json` output.
