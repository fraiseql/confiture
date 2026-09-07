"""The backfill yields between batches while other sessions wait for a lock on the table."""

from __future__ import annotations

from confiture.core.backfill import MAX_WAITER_PAUSES, yield_to_waiters


class _Connection:
    """A connection whose lock-waiter count comes from a script."""

    def __init__(self, counts: list[int]) -> None:
        self._counts = counts
        self.queries: list[str] = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, query: str, params: tuple = ()) -> None:
        self.queries.append(query)
        self._next = self._counts.pop(0) if self._counts else 0

    def fetchone(self) -> tuple[int]:
        return (self._next,)


def test_pauses_while_waiters_remain_then_proceeds() -> None:
    conn = _Connection([2, 1, 0])
    slept: list[float] = []

    pauses = yield_to_waiters(conn, "orders", 50, sleep=slept.append)

    assert pauses == 2
    assert slept == [0.05, 0.05]
    assert all("pg_locks" in q and "NOT l.granted" in q for q in conn.queries)


def test_the_guard_is_off_without_a_limit() -> None:
    conn = _Connection([5])
    assert yield_to_waiters(conn, "orders", None, sleep=lambda _s: None) == 0
    assert conn.queries == []


def test_the_pause_is_bounded() -> None:
    conn = _Connection([1] * (MAX_WAITER_PAUSES + 10))
    pauses = yield_to_waiters(conn, "orders", 1, sleep=lambda _s: None)
    assert pauses == MAX_WAITER_PAUSES
