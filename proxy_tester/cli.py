"""Command line entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import sys

from rich.console import Console

from . import __version__
from .checker import ProxyResult, fetch_real_ip, run_checks
from .geo import lookup_countries
from .parser import SUPPORTED_PROTOCOLS, parse_file
from .report import (
    final_table,
    result_line,
    summary_text,
    write_json,
    write_working,
)

console = Console()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="proxy-tester",
        description="Test HTTP/HTTPS/SOCKS4/SOCKS5 proxies from a file.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    test = sub.add_parser("test", help="test proxies from a list file")
    test.add_argument("file", help="proxy list file (ip:port or protocol://ip:port per line)")
    test.add_argument(
        "--protocol",
        choices=SUPPORTED_PROTOCOLS,
        default="http",
        help="protocol for bare ip:port lines (default: %(default)s)",
    )
    test.add_argument("--timeout", type=float, default=10.0, help="seconds per request (default: %(default)s)")
    test.add_argument("--concurrency", type=int, default=50, help="parallel tests (default: %(default)s)")
    test.add_argument(
        "--judge",
        default="https://api.iplocate.io/ip",
        help="URL fetched through the proxy (default: %(default)s)",
    )
    test.add_argument("--limit", type=int, help="only test the first N proxies")
    test.add_argument("--no-geo", action="store_true", help="skip country lookup")
    test.add_argument("--output", default="working.txt", help="working list file, '-' to skip (default: %(default)s)")
    test.add_argument("--json", default="results.json", help="full results file, '-' to skip (default: %(default)s)")
    test.add_argument("--sort", choices=("latency", "country", "protocol"), default="latency")
    test.add_argument("--show-failed", action="store_true", help="list failed proxies in the final table")
    return parser


async def run(args: argparse.Namespace) -> int:
    proxies, skipped = parse_file(args.file, args.protocol)
    if args.limit:
        proxies = proxies[: args.limit]
    if not proxies:
        console.print(f"[red]No usable proxies found in {args.file}[/]")
        return 1
    console.print(
        f"[bold]{len(proxies)}[/] proxies loaded"
        + (f" ({skipped} invalid/duplicate lines skipped)" if skipped else "")
        + f" · judge [cyan]{args.judge}[/]"
    )

    real_ip = await fetch_real_ip(args.judge)
    if real_ip:
        console.print(f"Your direct IP: [cyan]{real_ip}[/] (used for anonymity check)")
    else:
        console.print("[yellow]Could not fetch direct IP; anonymity check disabled[/]")

    results: list[ProxyResult] = []

    async def on_result(result: ProxyResult) -> None:
        results.append(result)
        console.print(result_line(result))

    try:
        await run_checks(
            proxies,
            judge=args.judge,
            timeout=args.timeout,
            concurrency=args.concurrency,
            on_result=on_result,
            real_ip=real_ip,
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        console.print("\n[yellow]Interrupted; reporting partial results[/]")

    working = [r for r in results if r.working]
    if working and not args.no_geo:
        exit_ips = [r.exit_ip for r in working if r.exit_ip]
        with console.status(f"Geolocating {len(set(exit_ips))} exit IPs..."):
            countries = await lookup_countries(exit_ips)
        for result in working:
            if result.exit_ip and result.exit_ip in countries:
                entry = countries[result.exit_ip]
                result.country = entry.get("country")
                result.country_code = entry.get("country_code")
                result.as_name = entry.get("as_name")
                result.as_registry = entry.get("as_registry")

    console.print()
    console.print(final_table(results, sort=args.sort, show_failed=args.show_failed))
    console.print(summary_text(results))

    if args.output != "-":
        count = write_working(results, args.output)
        console.print(f"[green]{count}[/] working proxies written to [cyan]{args.output}[/]")
    if args.json != "-":
        write_json(results, args.json, judge=args.judge)
        console.print(f"Full results written to [cyan]{args.json}[/]")

    return 0 if working else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
