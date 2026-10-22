# proxy-tester

Async CLI tool that tests HTTP, HTTPS, SOCKS4 and SOCKS5 proxies from a list
file: working or not, response latency, anonymity (does it hide your IP?) and
exit country.

## Install

With [uv](https://docs.astral.sh/uv/) (recommended, uses the committed `uv.lock`
for reproducible installs):

```bash
uv sync --extra dev
```

Or with plain pip:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Usage

```bash
# test a list (lines like "socks5://1.2.3.4:1080", "http://1.2.3.4:8080",
# or bare "1.2.3.4:8080" which uses --protocol, default http)
uv run proxy-tester test proxies.txt

# quick sample: only first 100 proxies, 5s timeout
uv run proxy-tester test proxies.txt --limit 100 --timeout 5

# free lists to try: https://github.com/iplocate/free-proxy-list
curl -s https://raw.githubusercontent.com/iplocate/free-proxy-list/main/all-proxies.txt -o proxies.txt
uv run proxy-tester test proxies.txt
```

Each proxy is tested by fetching the judge URL (default
`https://api.iplocate.io/ip`, free and unlimited) through the proxy:

- **working** — the judge answered with an IP
- **latency** — request duration in ms
- **anonymous** — the exit IP differs from your real IP
- **country** — exit IP geolocated in batches via ip-api.com (free, no key)

## Options

| Flag | Default | Description |
| --- | --- | --- |
| `--protocol` | `http` | Protocol for bare `ip:port` lines |
| `--timeout` | `10` | Seconds per proxy request |
| `--concurrency` | `50` | Parallel tests |
| `--judge` | `https://api.iplocate.io/ip` | Judge URL fetched through the proxy |
| `--limit` | all | Only test the first N proxies |
| `--no-geo` | off | Skip country lookup for working proxies |
| `--output` | `working.txt` | Working proxies file (`-` to skip) |
| `--json` | `results.json` | Full results file (`-` to skip) |
| `--sort` | `latency` | Final table order: `latency`, `country`, `protocol` |
| `--show-failed` | off | Include failed proxies in the final table |

Exit code is `0` when at least one proxy works, `1` otherwise.

## Development

```bash
uv sync --extra dev   # or: python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
uv run pytest         # or: .venv/bin/pytest
```

After changing dependencies in `pyproject.toml`, refresh the lockfile with
`uv lock` so it stays reproducible.
