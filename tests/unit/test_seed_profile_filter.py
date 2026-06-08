"""Unit tests for seed-profile filtering and config (P4, Cycles 1–2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.config.environment import SeedConfig, SeedProfile
from confiture.core.seed_applier import SeedApplier
from confiture.exceptions import ConfigurationError


def _seeds(tmp_path: Path, names: list[str]) -> Path:
    d = tmp_path / "seeds"
    d.mkdir()
    for n in names:
        (d / n).write_text("SELECT 1;")
    return d


class TestFindSeedFilesProfile:
    def test_none_returns_all_sorted(self, tmp_path: Path) -> None:
        d = _seeds(tmp_path, ["c.sql", "a.sql", "b.sql"])
        applier = SeedApplier(seeds_dir=d)
        assert [f.name for f in applier.find_seed_files()] == ["a.sql", "b.sql", "c.sql"]

    def test_exclude_filters_matching(self, tmp_path: Path) -> None:
        d = _seeds(tmp_path, ["a.sql", "stats_1.sql", "stats_2.sql", "c.sql"])
        applier = SeedApplier(seeds_dir=d)
        files = applier.find_seed_files(profile=SeedProfile(exclude=["stats_*.sql"]))
        assert [f.name for f in files] == ["a.sql", "c.sql"]

    def test_include_selects_only_matching(self, tmp_path: Path) -> None:
        d = _seeds(tmp_path, ["a.sql", "core_1.sql", "core_2.sql"])
        applier = SeedApplier(seeds_dir=d)
        files = applier.find_seed_files(profile=SeedProfile(include=["core_*.sql"]))
        assert [f.name for f in files] == ["core_1.sql", "core_2.sql"]

    def test_include_then_exclude(self, tmp_path: Path) -> None:
        d = _seeds(tmp_path, ["core_1.sql", "core_2.sql", "core_big.sql"])
        applier = SeedApplier(seeds_dir=d)
        files = applier.find_seed_files(
            profile=SeedProfile(include=["core_*.sql"], exclude=["core_big.sql"])
        )
        assert [f.name for f in files] == ["core_1.sql", "core_2.sql"]

    def test_order_preserved_after_filter(self, tmp_path: Path) -> None:
        d = _seeds(tmp_path, ["01_a.sql", "02_stats.sql", "03_b.sql"])
        applier = SeedApplier(seeds_dir=d)
        files = applier.find_seed_files(profile=SeedProfile(exclude=["*stats*"]))
        assert [f.name for f in files] == ["01_a.sql", "03_b.sql"]


class TestSeedConfigProfiles:
    def test_absent_profiles_defaults_empty(self) -> None:
        assert SeedConfig().profiles == {}

    def test_parses_profiles(self) -> None:
        cfg = SeedConfig(profiles={"slim": {"exclude": ["stats_*.sql"]}})
        assert cfg.profiles["slim"].exclude == ["stats_*.sql"]
        assert cfg.profiles["slim"].include == []

    def test_get_profile_returns_defined(self) -> None:
        cfg = SeedConfig(profiles={"slim": {"include": ["core_*.sql"]}})
        assert cfg.get_profile("slim").include == ["core_*.sql"]

    def test_get_profile_unknown_raises_config_error(self) -> None:
        cfg = SeedConfig(profiles={"slim": {}})
        with pytest.raises(ConfigurationError, match="Unknown seed profile"):
            cfg.get_profile("nope")

    def test_get_profile_lists_defined_in_message(self) -> None:
        cfg = SeedConfig(profiles={"slim": {}, "full": {}})
        with pytest.raises(ConfigurationError, match="full, slim"):
            cfg.get_profile("nope")
