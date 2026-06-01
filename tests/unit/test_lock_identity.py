"""Unit tests for lock-holder identity collection (issue #147, Phase 1)."""

from __future__ import annotations

import os
import socket

from confiture.core.locking import LockHolder, LockIdentity, collect_lock_identity


def test_collects_identity(monkeypatch) -> None:
    monkeypatch.setattr(socket, "gethostname", lambda: "deploy-host-1")
    monkeypatch.setattr(os, "getpid", lambda: 12345)
    ident = collect_lock_identity(command="confiture migrate up")
    assert ident.pid == 12345
    assert ident.hostname == "deploy-host-1"
    assert ident.command == "confiture migrate up"


def test_identity_is_a_dataclass() -> None:
    ident = LockIdentity(pid=1, hostname="h", command="c", user="u")
    assert (ident.pid, ident.hostname, ident.command, ident.user) == (1, "h", "c", "u")


def test_command_defaults_when_none(monkeypatch) -> None:
    monkeypatch.setattr(os, "getpid", lambda: 9)
    ident = collect_lock_identity(command=None)
    # Falls back to a generic confiture label rather than leaking argv.
    assert ident.command == "confiture"


def test_lock_holder_held_for_seconds_and_to_dict() -> None:
    holder = LockHolder(
        pid=12345,
        hostname="deploy-host-1",
        user="deploy",
        command="confiture migrate up",
        acquired_at="2026-05-31T14:30:00+00:00",
        held_for_seconds=47,
        live=True,
    )
    d = holder.to_dict()
    assert d["pid"] == 12345
    assert d["hostname"] == "deploy-host-1"
    assert d["command"] == "confiture migrate up"
    assert d["acquired_at"] == "2026-05-31T14:30:00+00:00"
    assert d["held_for_seconds"] == 47
    # `live` is internal liveness, not part of the public holder contract.
    assert "live" not in d
