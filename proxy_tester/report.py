"""Result presentation: rich tables and output files."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from rich import box
from rich.table import Table
from rich.text import Text

from . import __version__
from .checker import ProxyResult

_SORT_KEYS = {
    "latency": lambda r: (r.latency_ms is None, r.latency_ms or 0.0),
    "country": lambda r: (r.country or "zz", r.latency_ms or 0.0),
    "protocol": lambda r: (r.proxy.protocol, r.latency_ms or 0.0),
}


def _anon_text(anonymous: bool | None) -> Text:
    if anonymous is None:
        return Text("?", style="dim")
    return Text("yes" if anonymous else "NO", style="green" if anonymous else "red")


def _latency_text(result: ProxyResult) -> str:
    if result.latency_ms is None:
        return "-"
    style = "green" if result.latency_ms < 1000 else ("yellow" if result.latency_ms < 3000 else "red")
    return f"[{style}]{result.latency_ms:.0f} ms[/]"


def result_line(result: ProxyResult) -> Text:
    """Single-line, scrollback-friendly log for one finished test."""
    line = Text(no_wrap=True, overflow="ellipsis")
    if result.working:
        line.append("✔ ", style="green")
        line.append(str(result.proxy).ljust(34))
        line.append(f"{result.latency_ms:7.0f} ms  ")
        if result.exit_ip:
            line.append(f"exit {result.exit_ip}", style="cyan")
        if result.anonymous:
            line.append("  anon", style="green")
        elif result.anonymous is False:
            line.append("  NOT anon", style="bold red")
    else:
        line.append("✘ ", style="red")
        line.append(str(result.proxy).ljust(34), style="dim")
        line.append((result.error or "failed")[:44], style="red")
    return line


def final_table(
    results: list[ProxyResult],
    sort: str = "latency",
    show_failed: bool = False,
) -> Table:
    """Full result table, working proxies first, sorted as requested."""
    key = _SORT_KEYS.get(sort, _SORT_KEYS["latency"])
    working = sorted((r for r in results if r.working), key=key)
    failed = sorted(
        (r for r in results if not r.working),
        key=lambda r: (r.error or "",),
    )

    table = Table(box=box.ROUNDED, title="Proxy test results")
    # Fixed widths keep the small columns from being crushed on narrow terminals.
    table.add_column("Proxy", no_wrap=True, overflow="fold")
    table.add_column("Proto", no_wrap=True, width=6)
    table.add_column("Status", no_wrap=True, width=7)
    table.add_column("Latency", justify="right", no_wrap=True, width=9)
    table.add_column("Exit IP", no_wrap=True, width=15)
    table.add_column("AS", ratio=2, min_width=18, overflow="fold")
    table.add_column("Anon", no_wrap=True, width=4)
    table.add_column("Country", ratio=1, min_width=8, overflow="fold")

    for result in working:
        table.add_row(
            str(result.proxy),
            result.proxy.protocol,
            "[green]working[/]",
            _latency_text(result),
            result.exit_ip or "-",
            result.as_name or "-",
            _anon_text(result.anonymous),
            result.country or "-",
        )
    if show_failed:
        for result in failed:
            table.add_row(
                str(result.proxy),
                result.proxy.protocol,
                "[red]failed[/]",
                "-",
                "-",
                "-",
                "-",
                "-",
            )
        if failed:
            table.add_section()
            table.add_row(
                f"[dim]{len(failed)} failed (shown with --show-failed)[/]",
                "", "", "", "", "", "", "",
            )
    elif failed:
        table.caption = f"{len(failed)} failed (hidden, use --show-failed)"
    return table


def summary_text(results: list[ProxyResult]) -> Text:
    working = [r for r in results if r.working]
    anonymous = [r for r in working if r.anonymous]
    latencies = [r.latency_ms for r in working if r.latency_ms is not None]
    parts = [
        f"tested {len(results)}",
        f"[green]working {len(working)}[/]",
        f"[red]failed {len(results) - len(working)}[/]",
    ]
    if latencies:
        avg = sum(latencies) / len(latencies)
        best = min(latencies)
        parts.append(f"avg [bold]{avg:.0f} ms[/], best [bold]{best:.0f} ms[/]")
    if anonymous:
        parts.append(f"anonymous [bold]{len(anonymous)}[/]")
    return Text.from_markup(" · ".join(parts))


def write_working(results: list[ProxyResult], path: str) -> int:
    """Write working proxies as protocol://ip:port lines. Returns count."""
    working = [r for r in results if r.working]
    with open(path, "w", encoding="utf-8") as fh:
        for result in working:
            fh.write(result.proxy.url + "\n")
    return len(working)


def write_json(
    results: list[ProxyResult],
    path: str,
    judge: str | None = None,
) -> None:
    payload = {
        "tool": "proxy-tester",
        "version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "judge": judge,
        "counts": {
            "total": len(results),
            "working": sum(1 for r in results if r.working),
        },
        "results": [r.to_dict() for r in results],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
