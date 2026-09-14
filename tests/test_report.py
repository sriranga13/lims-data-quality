import json

from lims_dq.report import ErrorReport, ValidationError


def make_error(row=2, column="unit", rule="constraint"):
    return ValidationError(
        row=row,
        column=column,
        value="kg",
        rule=rule,
        message="'kg' is not one of ['mg/L', 'ug/mL']",
    )


def passing_report():
    return ErrorReport(
        filename="good.csv",
        ruleset_name="lims-export",
        ruleset_version="1.0.0",
        rows_checked=50,
        errors=[],
    )


def failing_report():
    return ErrorReport(
        filename="bad.csv",
        ruleset_name="lims-export",
        ruleset_version="1.0.0",
        rows_checked=10,
        errors=[make_error(row=2), make_error(row=2, column="sample_id"),
                make_error(row=5, column="unit")],
    )


def test_passed_property():
    assert passing_report().passed is True
    assert failing_report().passed is False


def test_row_counts():
    r = failing_report()
    assert r.rows_failed == 2  # rows 2 and 5 (row 2 has two errors)
    assert r.rows_passed == 8


def test_to_dict_summary():
    d = failing_report().to_dict()
    assert d["filename"] == "bad.csv"
    assert d["ruleset"] == {"name": "lims-export", "version": "1.0.0"}
    summary = d["summary"]
    assert summary["rows_checked"] == 10
    assert summary["error_count"] == 3
    assert summary["errors_by_column"] == {"unit": 2, "sample_id": 1}
    assert summary["errors_by_rule"] == {"constraint": 3}
    assert len(d["errors"]) == 3
    assert d["errors"][0]["row"] == 2


def test_to_json_round_trip():
    payload = json.loads(failing_report().to_json())
    assert payload["summary"]["error_count"] == 3


def test_to_text_pass():
    text = passing_report().to_text()
    assert "PASS" in text
    assert "50" in text


def test_to_text_fail_lists_rows():
    text = failing_report().to_text()
    assert "row" in text and "column" in text
    assert "unit" in text
    assert "'kg' is not one of" in text
