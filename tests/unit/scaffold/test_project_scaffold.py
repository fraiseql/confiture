"""What ``confiture init`` writes: package templates, copied under the project's ``db/``."""

from pathlib import Path

import yaml

from confiture.config.environment import migration_block
from confiture.core.scaffold.project import scaffold


def test_scaffold_writes_every_template_and_every_directory(tmp_path: Path) -> None:
    db = tmp_path / "db"
    written = scaffold(db)

    assert sorted(p.relative_to(db).as_posix() for p in written) == [
        "README.md",
        "environments/local.yaml",
        "schema/00_common/extensions.sql",
        "schema/10_tables/example.sql",
        "seeds/common/00_example.sql",
    ]
    for directory in ("migrations", "seeds/development", "seeds/test"):
        assert (db / directory).is_dir()


def test_the_local_environment_is_a_valid_config(tmp_path: Path) -> None:
    local = (tmp_path / "db").joinpath("environments", "local.yaml")
    scaffold(tmp_path / "db")
    data = yaml.safe_load(local.read_text())
    assert migration_block(data, local).tracking_table == "tb_confiture"
