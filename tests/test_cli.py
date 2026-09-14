import json

import pytest

from lims_dq.cli import main

SCHEMA = {
    "name": "lims-export",
    "version": "1.0.0",
    "columns": {
        "sample_id": {
            "dtype": "string",
            "required": True,
            "pattern": "^SMP-[0-9]{6}$",
        },
        "concentration": {"dtype": "float", "required": True, "min": 0.0, "max": 100.0},
        "unit": {"dtype": "string", "required": True, "allowed": ["mg/L", "ug/mL"]},
    },
}

GOOD_CSV = (
    "sample_id,concentration,unit\n"
    "SMP-000001,12.5,mg/L\n"
    "SMP-000002,0.5,ug/mL\n"
)

BAD_CSV = (
    "sample_id,concentration,unit\n"
    "SMP-000001,12.5,mg/L\n"
    "WRONG-ID,9999,kg\n"
)


@pytest.fixture
def files(tmp_path):
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps(SCHEMA), encoding="utf-8")
    good = tmp_path / "good.csv"
    good.write_text(GOOD_CSV, encoding="utf-8")
    bad = tmp_path / "bad.csv"
    bad.write_text(BAD_CSV, encoding="utf-8")
    return schema, good, bad


def test_validate_pass_exit_zero(files, capsys):
    schema, good, _ = files
    assert main(["validate", str(good), "--schema", str(schema)]) == 0
    assert "PASS" in capsys.readouterr().out


def test_validate_fail_exit_one(files, capsys):
    schema, _, bad = files
    assert main(["validate", str(bad), "--schema", str(schema)]) == 1
    out = capsys.readouterr().out
    assert "WRONG-ID" in out or "pattern" in out


def test_missing_data_file_exit_two(files, tmp_path, capsys):
    schema, _, _ = files
    assert main(["validate", str(tmp_path / "nope.csv"), "--schema", str(schema)]) == 2


def test_bad_schema_exit_two(tmp_path, capsys):
    bad_schema = tmp_path / "schema.json"
    bad_schema.write_text('{"nope": true}', encoding="utf-8")
    data = tmp_path / "d.csv"
    data.write_text(GOOD_CSV, encoding="utf-8")
    assert main(["validate", str(data), "--schema", str(bad_schema)]) == 2


def test_report_flag_writes_json(files, tmp_path):
    schema, _, bad = files
    report_path = tmp_path / "report.json"
    assert main(["validate", str(bad), "--schema", str(schema),
                 "--report", str(report_path)]) == 1
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["summary"]["error_count"] == 3
    assert payload["filename"] == "bad.csv"


def test_audit_log_flag_appends_entry(files, tmp_path):
    schema, good, _ = files
    log = tmp_path / "audit.jsonl"
    assert main(["validate", str(good), "--schema", str(schema),
                 "--audit-log", str(log)]) == 0
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["passed"] is True
    assert entry["rows_checked"] == 2
    assert entry["ruleset_version"] == "1.0.0"


def test_no_strict_ignores_extra_columns(files, tmp_path):
    schema, _, _ = files
    data = tmp_path / "extra.csv"
    data.write_text(
        "sample_id,concentration,unit,notes\nSMP-000001,1.0,mg/L,hi\n",
        encoding="utf-8",
    )
    assert main(["validate", str(data), "--schema", str(schema)]) == 1  # strict
    assert main(["validate", str(data), "--schema", str(schema),
                 "--no-strict"]) == 0
