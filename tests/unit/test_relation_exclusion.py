"""``diff.exclude``: the relations another tool owns, left out of every comparison (#767)."""

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.differ import SchemaDiffer, Side, stated_side, without
from confiture.core.relation_exclusion import Exclusion, RelationPattern, exclusion_from
from confiture.core.schema_model import SchemaModel, Table, Trigger, ref_for, trigger_ref
from confiture.core.schema_read import read_text
from confiture.core.seed.drift import scope_for
from confiture.exceptions import ConfigurationError

runner = CliRunner()


class TestPattern:
    def test_a_pattern_with_no_dot_matches_the_name_in_any_schema(self) -> None:
        pattern = RelationPattern.of("_fraiseql_meta")
        assert pattern.matches("public", "_fraiseql_meta")
        assert pattern.matches("app", "_fraiseql_meta")
        assert not pattern.matches("public", "_fraiseql_meta2")

    def test_a_pattern_with_a_dot_matches_that_schema_only(self) -> None:
        pattern = RelationPattern.of("public._fraiseql_meta")
        assert (pattern.schema, pattern.name) == ("public", "_fraiseql_meta")
        assert pattern.matches("public", "_fraiseql_meta")
        assert not pattern.matches("app", "_fraiseql_meta")

    def test_each_part_is_a_glob(self) -> None:
        assert RelationPattern.of("_fraiseql_*").matches("public", "_fraiseql_cron_state")
        assert RelationPattern.of("app*._fraiseql_?").matches("app_2", "_fraiseql_x")
        assert RelationPattern.of("tb_[ab]").matches("public", "tb_a")
        assert not RelationPattern.of("tb_[ab]").matches("public", "tb_c")
        assert not RelationPattern.of("app*._fraiseql_*").matches("public", "_fraiseql_x")

    def test_a_pattern_is_case_sensitive(self) -> None:
        assert not RelationPattern.of("_FraiseQL_*").matches("public", "_fraiseql_meta")

    @pytest.mark.parametrize("written", ["", "a.b.c", "a b", "a;b", "a.", "-- x"])
    def test_what_is_not_a_relation_pattern_is_refused(self, written: str) -> None:
        with pytest.raises(ConfigurationError) as caught:
            RelationPattern.of(written)
        assert caught.value.error_code == "CONFIG_001"


class TestConfig:
    def test_the_config_and_the_cli_add_up_once_each(self) -> None:
        exclusion = exclusion_from({"diff": {"exclude": ["a_*", "b"]}}, ["b", "c"])
        assert [p.written for p in exclusion.patterns] == ["a_*", "b", "c"]

    def test_no_block_excludes_nothing(self) -> None:
        assert not exclusion_from({}, None)

    @pytest.mark.parametrize("block", [5, {"exclude": "a_*"}, {"exclude": [1]}])
    def test_a_malformed_block_is_a_configuration_error(self, block: object) -> None:
        with pytest.raises(ConfigurationError) as caught:
            exclusion_from({"diff": block})
        assert caught.value.error_code == "CONFIG_001"


TREE = """
CREATE TABLE app_user (id BIGINT PRIMARY KEY);
CREATE TABLE _fraiseql_meta (id SERIAL PRIMARY KEY, k TEXT);
CREATE INDEX _fraiseql_meta_k ON _fraiseql_meta (k);
CREATE SEQUENCE _fraiseql_seq;
CREATE VIEW _fraiseql_v AS SELECT 1 AS one;
CREATE FUNCTION touch() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$;
"""

#: TREE without another tool's relations.
OURS = "\n".join(line for line in TREE.splitlines() if "_fraiseql" not in line)

FRAISEQL = Exclusion.of(["_fraiseql_*"])


class TestSide:
    def test_an_excluded_relation_goes_with_what_belongs_to_it(self) -> None:
        side = without(Side.of(read_text(TREE)), FRAISEQL)
        assert [t.name for t in side.tables] == ["app_user"]
        assert side.sequences == []
        assert not side.model.views
        assert all(not ref.name.startswith("_fraiseql") for ref in side.objects)
        assert side.warnings == []

    def test_a_side_without_an_excluded_relation_is_unchanged(self) -> None:
        side = Side.of(read_text(TREE))
        assert without(side, Exclusion.of(["nothing_*"])) == side

    def test_the_trigger_on_one_goes_with_it_and_a_tree_says_so(self) -> None:
        sql = TREE + "CREATE TRIGGER t BEFORE UPDATE ON _fraiseql_meta "
        sql += "FOR EACH ROW EXECUTE FUNCTION touch();\n"
        side = without(Side.of(read_text(sql)), FRAISEQL)
        assert not side.model.triggers
        assert not any(ref.kind == "trigger" for ref in side.objects)
        (note,) = side.warnings
        assert note.code == "DIFFER_411"
        assert "public._fraiseql_meta" in note.message

    def test_a_database_owns_the_triggers_on_its_tools_tables(self) -> None:
        trigger = Trigger("t", "_fraiseql_meta")
        model = SchemaModel(
            tables={ref_for("table", None, "_fraiseql_meta"): Table("_fraiseql_meta")},
            triggers={trigger_ref(trigger): trigger},
            source="catalog",
        )
        side = without(stated_side(model), FRAISEQL)
        assert not side.model.triggers
        assert side.warnings == []

    def test_an_index_a_tree_writes_on_an_excluded_relation_it_does_not_declare_is_said(
        self,
    ) -> None:
        side = without(Side.of(read_text("CREATE INDEX i ON _fraiseql_x (k);")), FRAISEQL)
        assert not side.dangling
        assert [w.code for w in side.warnings] == ["DIFFER_411"]


class TestComparison:
    def test_an_excluded_relation_on_one_side_is_no_change(self) -> None:
        old = Side.of(read_text(TREE))
        new = Side.of(read_text(OURS))
        assert SchemaDiffer().compare_sides(old, new).changes
        diff = SchemaDiffer().compare_sides(old, new, exclude=FRAISEQL)
        assert diff.changes == []

    def test_a_foreign_key_to_an_excluded_relation_is_said_once(self) -> None:
        sql = TREE + "CREATE TABLE note (id INT, m INT REFERENCES _fraiseql_meta);\n"
        diff = SchemaDiffer().compare_sides(
            Side.of(read_text(sql)), Side.of(read_text(sql)), exclude=FRAISEQL
        )
        assert diff.changes == []
        (note,) = diff.warnings
        assert note.code == "DIFFER_411"
        assert "foreign key 'note." in note.message
        assert "public._fraiseql_meta" in note.message


@pytest.fixture
def seeded(tmp_path: Path) -> Iterator[Path]:
    schema = tmp_path / "db" / "schema"
    (schema / "seeds").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (schema / "t.sql").write_text(
        "CREATE TABLE app.t (k text PRIMARY KEY);\nCREATE TABLE app._fraiseql_x (k text PRIMARY KEY);\n"
    )
    (schema / "seeds" / "s.sql").write_text(
        "INSERT INTO app.t (k) VALUES ('a');\nINSERT INTO app._fraiseql_x (k) VALUES ('a');\n"
    )
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://127.0.0.1:1/confiture_no_such_server\n"
        "include_dirs:\n  - path: db/schema\n"
    )
    old = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old)


class TestSeedDrift:
    def _scope(self) -> dict:
        result = runner.invoke(app, ["seed", "drift", "--list-scope", "--format", "json"])
        assert result.exit_code == 0, result.output
        return json.loads(result.stdout)

    def test_a_table_the_environment_excludes_is_skipped_with_its_pattern(
        self, seeded: Path
    ) -> None:
        assert "app._fraiseql_x" in json.dumps(self._scope()["scope"])
        env = seeded / "db" / "environments" / "local.yaml"
        env.write_text(env.read_text() + "diff:\n  exclude: ['app._fraiseql_*']\n")
        payload = self._scope()
        assert "_fraiseql_x" not in json.dumps(payload["scope"])
        assert payload["skipped"] == [
            {"table": "app._fraiseql_x", "reason": "diff.exclude: app._fraiseql_*"}
        ]

    def test_a_library_caller_adds_patterns_to_the_environments(self, seeded: Path) -> None:
        report = scope_for("local", exclude=["_fraiseql_?"])
        assert report.skipped == (("app._fraiseql_x", "diff.exclude: _fraiseql_?"),)
