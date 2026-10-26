"""How ``confiture seed drift`` prints what it compares, and what it found."""

from confiture.cli.markup import Printer, Table
from confiture.core.seed.drift import Key, SeedDriftReport, TableDrift, field_name

#: How many keys a table's findings list before saying how many more there are.
SHOWN = 10


def _key(key: Key) -> str:
    return ", ".join("NULL" if part is None else part for part in key)


def print_scope(report: SeedDriftReport, out: Printer) -> None:
    """The tables a run compares, each key and its basis, and the columns it compares."""
    table = Table("Table", "Key", "Basis", "Mode", "Compared")
    for scoped in report.scope.tables:
        key = ", ".join(field_name(f) for f in scoped.key)
        compared = ", ".join(field_name(f) for f in scoped.columns) or "(the key alone)"
        table.add_row(
            t"{scoped.relation.qualified}",
            t"{key}",
            t"{scoped.key_basis}",
            t"{scoped.mode}",
            t"{compared}",
        )
    out.print(table)
    for scoped in report.scope.tables:
        for column, why in scoped.uncompared:
            out.print(t"[dim]{scoped.relation.qualified}.{column} is not compared: {why}[/dim]")


def _keys(out: Printer, label: str, keys: tuple[Key, ...]) -> None:
    for key in keys[:SHOWN]:
        out.print(t"    {label} {_key(key)}")
    if len(keys) > SHOWN:
        out.print(t"    … and {len(keys) - SHOWN} more {label}")


def _table_findings(out: Printer, drift: TableDrift) -> None:
    out.print(t"[bold]{drift.table}[/bold] (key {', '.join(drift.key)})")
    _keys(out, "seed only:", drift.seed_only)
    _keys(out, "live only:", drift.live_only)
    for row in drift.changed[:SHOWN]:
        out.print(t"    changed:   {_key(row.key)}")
        for name, seed, live in row.columns:
            out.print(t"      {name}: {seed!r} → {live!r}")
    if len(drift.changed) > SHOWN:
        out.print(t"    … and {len(drift.changed) - SHOWN} more changed")
    _keys(out, "accepted:", drift.accepted)


def _left_out(report: SeedDriftReport, out: Printer) -> None:
    for entry in report.not_compared:
        where = f" ({entry.where})" if entry.where else ""
        out.print(t"[yellow]not compared[/yellow] {entry.table}{where}: {entry.reason}")
    for name, reason in report.skipped:
        out.print(t"[dim]skipped[/dim] {name}: {reason}")
    for unused in report.unused:
        out.print(t"[yellow]⚠[/yellow] {unused}")


def print_report(report: SeedDriftReport, out: Printer) -> None:
    """A run: each table's counts, then every difference, then what was left out and why."""
    if not report.compared:
        print_scope(report, out)
        _left_out(report, out)
        return
    out.print(t"Seed side: {report.seed_side}; live side: {report.against}")
    table = Table("Table", "Seed rows", "Live rows", "Seed only", "Live only", "Changed")
    for drift in report.tables:
        live = f"{drift.live_rows} (seed keys)" if drift.mode == "subset" else str(drift.live_rows)
        table.add_row(
            t"{drift.table}",
            t"{drift.seed_rows}",
            t"{live}",
            t"{len(drift.seed_only)}",
            t"{len(drift.live_only)}",
            t"{len(drift.changed)}",
        )
    out.print(table)
    for drift in report.tables:
        if drift.drifted:
            _table_findings(out, drift)
    _left_out(report, out)
    drifted = sum(1 for d in report.tables if d.drifted)
    missing = len(report.not_compared)
    if not report.tables and missing:
        out.print(t"[yellow]⚠ nothing was compared; {missing} not compared (see above)[/yellow]")
    elif report.has_drift:
        out.print(
            t"[red]❌ {drifted} of {len(report.tables)} compared tables drifted; "
            t"{missing} not compared[/red]"
        )
    elif missing:
        out.print(t"[yellow]⚠ no drift in what was compared; {missing} not compared[/yellow]")
    else:
        out.print(t"[green]✅ the live side holds every seeded row, as seeded[/green]")
