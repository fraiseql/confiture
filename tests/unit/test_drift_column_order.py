"""``column_order_mismatch``: the differ compares column ordinal position (#226).

Both sides already carried the order — the expected DDL in declaration order,
the live side by ``ordinal_position`` — and the differ never read it. One
warning per table whose columns are the same set in a different order;
nothing when the sets differ (the missing/extra items already say so);
``--ignore-column-order`` or ``drift.ignore_column_order`` turns it off;
``drift.column_order_severity: critical`` promotes it to a failing item.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.config.environment import DriftConfig
from confiture.core.drift import DriftSeverity, DriftType, SchemaDriftDetector
from confiture.core.schema_analyzer import SchemaInfo
from confiture.core.schema_exporter import load_schema

COLS = {
    "id": {"type": "bigint", "nullable": False},
    "name": {"type": "text", "nullable": True},
    "created_at": {"type": "timestamp", "nullable": True},
}


def _info(order: list[str], table: str = "tenant.tb_user") -> SchemaInfo:
    return SchemaInfo(tables={table: {c: COLS[c] for c in order}})


def _detector(**kwargs) -> SchemaDriftDetector:  # type: ignore[no-untyped-def]
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("db",)
    return SchemaDriftDetector(conn, **kwargs)


def _order_items(report):  # type: ignore[no-untyped-def]
    return [i for i in report.drift_items if i.drift_type == DriftType.COLUMN_ORDER_MISMATCH]


def test_same_columns_in_a_different_order_is_one_warning_per_table() -> None:
    report = _detector().compare_schemas(
        _info(["id", "name", "created_at"]), _info(["id", "created_at", "name"])
    )
    (item,) = _order_items(report)
    assert item.severity == DriftSeverity.WARNING
    assert item.object_name == "tenant.tb_user"
    assert item.details == {
        "expected_order": ["id", "name", "created_at"],
        "actual_order": ["id", "created_at", "name"],
    }
    assert item.expected == "id, name, created_at"
    assert item.actual == "id, created_at, name"
    assert item.to_dict()["type"] == "column_order_mismatch"
    assert item.to_dict()["details"] == item.details
    assert not report.has_critical_drift


def test_different_column_sets_produce_no_order_item() -> None:
    report = _detector().compare_schemas(
        _info(["id", "name", "created_at"]), _info(["id", "created_at"])
    )
    assert _order_items(report) == []
    assert [i.drift_type for i in report.drift_items] == [DriftType.MISSING_COLUMN]


def test_identical_order_is_quiet() -> None:
    report = _detector().compare_schemas(_info(["id", "name"]), _info(["id", "name"]))
    assert report.drift_items == []


def test_the_check_can_be_turned_off() -> None:
    report = _detector(ignore_column_order=True).compare_schemas(
        _info(["id", "name"]), _info(["name", "id"])
    )
    assert report.drift_items == []


def test_severity_can_be_promoted_to_critical() -> None:
    report = _detector(column_order_severity="critical").compare_schemas(
        _info(["id", "name"]), _info(["name", "id"])
    )
    (item,) = _order_items(report)
    assert item.severity == DriftSeverity.CRITICAL
    assert report.has_critical_drift


def test_drift_config_defaults_and_wiring() -> None:
    cfg = DriftConfig()
    assert cfg.ignore_column_order is False
    assert cfg.column_order_severity == "warning"
    detector = _detector(
        ignore_column_order=cfg.ignore_column_order, column_order_severity=cfg.column_order_severity
    )
    (item,) = _order_items(detector.compare_schemas(_info(["id", "name"]), _info(["name", "id"])))
    assert item.severity == DriftSeverity.WARNING


def test_an_order_item_validates_against_the_drift_schema() -> None:
    report = _detector().compare_schemas(_info(["id", "name"]), _info(["name", "id"]))
    common = Resource.from_contents(load_schema("_common.schema.json"))
    registry = Registry().with_resource("_common.schema.json", common)
    validator = Draft202012Validator(load_schema("drift.schema.json"), registry=registry)
    payload = {**report.to_dict(), "hints": []}
    assert list(validator.iter_errors(payload)) == []
    assert payload["drift_items"][0]["type"] == "column_order_mismatch"


class TestCliFlags:
    @patch("confiture.cli.commands.drift.SchemaDriftDetector")
    @patch("confiture.cli.commands.drift.open_connection")
    @patch("confiture.cli.commands.drift.load_config")
    def test_drift_passes_the_flag_and_config_to_the_detector(
        self, mock_load, mock_open, mock_cls, tmp_path
    ) -> None:
        mock_load.return_value = {
            "database_url": "postgresql://x/y",
            "drift": {"column_order_severity": "critical"},
        }
        mock_open.return_value.__enter__.return_value = MagicMock()
        mock_cls.return_value.compare_with_schema_file.return_value = MagicMock(
            has_critical_drift=False, has_drift=False, to_dict=lambda: {}, drift_items=[]
        )
        schema = tmp_path / "s.sql"
        schema.write_text("CREATE TABLE t (id int);")
        cfg = tmp_path / "confiture.yaml"
        cfg.write_text("database_url: postgresql://x/y\n")
        result = CliRunner().invoke(
            app, ["drift", "--config", str(cfg), "--schema", str(schema), "--ignore-column-order"]
        )
        assert result.exit_code == 0, result.output
        _, kwargs = mock_cls.call_args
        assert kwargs["ignore_column_order"] is True
        assert kwargs["column_order_severity"] == "critical"
