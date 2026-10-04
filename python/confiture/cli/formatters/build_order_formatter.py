"""Output for ``build --list-files --compare-to``: the files whose build order moved since a ref."""

from confiture.cli.formatters.common import handle_output
from confiture.cli.markup import Printer
from confiture.core.build_order import Move, OrderComparison


def comparison_payload(comparison: OrderComparison, *, env: str, ref: str) -> dict:
    """The ``--compare-to`` payload: what was compared, then the comparison."""
    return {"env": env, "ref": ref, **comparison.to_dict()}


def _place(tense: str, after: str | None, before: str | None) -> str:
    if after is None and before is None:
        return f"{tense} alone"
    if after is None:
        return f"{tense} first, before {before}"
    if before is None:
        return f"{tense} after {after}, last"
    return f"{tense} after {after}, before {before}"


def _print_move(console: Printer, move: Move, *, allowed: bool) -> None:
    console.print(t"  {move.path}", soft_wrap=True)
    console.print(t"    {_place('was', move.was_after, move.was_before)}", soft_wrap=True)
    console.print(t"    {_place('now', move.now_after, move.now_before)}", soft_wrap=True)
    if allowed:
        console.print("    [dim](allowed)[/dim]")


def format_order_comparison(
    comparison: OrderComparison,
    *,
    env: str,
    ref: str,
    format_type: str,
    console: Printer,
) -> None:
    """Print the comparison: a summary line, then each moved file with its neighbours.

    Args:
        comparison: The build order at *ref* against the working tree's.
        env: The environment both sides selected for.
        ref: The git revision compared against.
        format_type: ``text``, ``json`` or ``csv``.
        console: Where it is printed.
    """
    if format_type == "text":
        files, renamed = comparison.files, len(comparison.renamed)
        if not comparison.moved:
            console.print(t"{files} files, {renamed} renamed, order preserved", soft_wrap=True)
        else:
            console.print(
                t"{files} files, {renamed} renamed, order preserved except:", soft_wrap=True
            )
            for move in comparison.moved:
                _print_move(console, move, allowed=move.path in comparison.allowed)
        if comparison.added or comparison.removed:
            console.print(
                t"{len(comparison.added)} added, {len(comparison.removed)} removed since {ref}",
                soft_wrap=True,
            )
        return

    csv_data = (
        ["path", "was_after", "was_before", "now_after", "now_before", "allowed"],
        [
            [
                move.path,
                move.was_after or "",
                move.was_before or "",
                move.now_after or "",
                move.now_before or "",
                str(move.path in comparison.allowed),
            ]
            for move in comparison.moved
        ],
    )
    handle_output(
        format_type, comparison_payload(comparison, env=env, ref=ref), csv_data, None, console
    )
