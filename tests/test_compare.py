"""Tests for lims_dq.compare and the ``lims-dq compare`` CLI."""

import json

import pandas as pd
import pytest

from lims_dq.compare import (
    ChangedCell,
    CompareError,
    ComparisonResult,
    compare_dataframes,
)


def _frame(rows):
    return pd.DataFrame(rows)


BEFORE = _frame(
    [
        {"sample_id": "SMP-000001", "concentration": "12.5", "unit": "mg/L"},
        {"sample_id": "SMP-000002", "concentration": "0.1", "unit": "mg/L"},
        {"sample_id": "SMP-000003", "concentration": "ND", "unit": "mg/L"},
    ]
)


def test_identical_frames():
    result = compare_dataframes(BEFORE, BEFORE.copy(), key="sample_id")
    assert result.identical
    assert result.matched_rows == 3
    assert result.identical_rows == 3
    assert result.changed_rows == 0
    assert result.diff_count == 0
    assert result.to_dict()["identical"] is True
    assert "identical" in result.to_text()


def test_changed_cell():
    after = BEFORE.copy()
    after.loc[1, "concentration"] = "0.2"
    result = compare_dataframes(
        BEFORE, after, key="sample_id", before_name="a.csv", after_name="b.csv"
    )
    assert not result.identical
    assert result.changed_rows == 1
    assert result.identical_rows == 2
    assert len(result.changed_cells) == 1
    cell = result.changed_cells[0]
    assert (cell.key, cell.column, cell.before, cell.after) == (
        "SMP-000002",
        "concentration",
        "0.1",
        "0.2",
    )
    text = result.to_text()
    assert "SMP-000002" in text and "concentration" in text


def test_rows_only_on_one_side():
    after = BEFORE.iloc[:2].copy()  # drop SMP-000003
    extra = pd.DataFrame(
        [{"sample_id": "SMP-000009", "concentration": "5.0", "unit": "mg/L"}]
    )
    after = pd.concat([after, extra], ignore_index=True)
    result = compare_dataframes(BEFORE, after, key="sample_id")
    assert result.only_in_before == ["SMP-000003"]
    assert result.only_in_after == ["SMP-000009"]
    assert result.matched_rows == 2
    assert result.diff_count == 2


def test_columns_only_on_one_side():
    after = BEFORE.copy()
    after["analyst"] = "ks"
    result = compare_dataframes(BEFORE, after, key="sample_id")
    assert result.columns_only_in_after == ["analyst"]
    assert result.columns_only_in_before == []
    # shared columns still compared; no cell diffs
    assert not result.changed_cells
    assert not result.identical  # column presence difference counts


def test_numeric_tolerance_absorbs_rounding():
    after = BEFORE.copy()
    after.loc[1, "concentration"] = "0.1000001"
    strict = compare_dataframes(BEFORE, after, key="sample_id")
    assert strict.changed_rows == 1
    tolerant = compare_dataframes(
        BEFORE, after, key="sample_id", tolerance=1e-4
    )
    assert tolerant.identical


def test_whitespace_and_blank_normalization():
    before = _frame(
        [{"sample_id": "S1", "note": "  ok "}, {"sample_id": "S2", "note": ""}]
    )
    after = _frame(
        [{"sample_id": "S1", "note": "ok"}, {"sample_id": "S2", "note": "   "}]
    )
    result = compare_dataframes(before, after, key="sample_id")
    assert result.identical


def test_missing_key_column():
    with pytest.raises(CompareError, match="key column 'nope' not found"):
        compare_dataframes(BEFORE, BEFORE, key="nope")


def test_duplicate_keys_rejected():
    dup = pd.concat([BEFORE, BEFORE.iloc[:1]], ignore_index=True)
    with pytest.raises(CompareError, match="duplicate key"):
        compare_dataframes(dup, BEFORE, key="sample_id")


def test_empty_frame_rejected():
    with pytest.raises(CompareError, match="no rows"):
        compare_dataframes(BEFORE.iloc[:0], BEFORE, key="sample_id")


def test_negative_tolerance_rejected():
    with pytest.raises(CompareError, match="tolerance"):
        compare_dataframes(BEFORE, BEFORE, key="sample_id", tolerance=-1)


def test_to_dict_round_trip():
    after = BEFORE.copy()
    after.loc[0, "unit"] = "ug/mL"
    result = compare_dataframes(BEFORE, after, key="sample_id")
    payload = result.to_dict()
    assert payload["diff_count"] == 1
    assert payload["changed_cells"][0]["key"] == "SMP-000001"
    json.dumps(payload)  # must be JSON-serializable


def test_changed_cell_to_dict():
    cell = ChangedCell(key="S1", column="c", before="1", after="2")
    assert cell.to_dict() == {"key": "S1", "column": "c", "before": "1", "after": "2"}


# --- CLI tests ---


def _write_csv(tmp_path, name, rows):
    path = tmp_path / name
    pd.DataFrame(rows).to_csv(path, index=False)
    return str(path)


def test_cli_compare_identical(capsys, tmp_path):
    from lims_dq.cli import main

    rows = [{"sample_id": "S1", "v": "1.0"}]
    a = _write_csv(tmp_path, "a.csv", rows)
    b = _write_csv(tmp_path, "b.csv", rows)
    assert main(["compare", a, b, "--key", "sample_id"]) == 0
    assert "identical" in capsys.readouterr().out


def test_cli_compare_diffs_and_report(capsys, tmp_path):
    from lims_dq.cli import main

    a = _write_csv(tmp_path, "a.csv", [{"sample_id": "S1", "v": "1.0"}])
    b = _write_csv(tmp_path, "b.csv", [{"sample_id": "S1", "v": "2.0"}])
    report = tmp_path / "cmp.json"
    assert main(["compare", a, b, "--key", "sample_id", "--report", str(report)]) == 1
    payload = json.loads(report.read_text())
    assert payload["diff_count"] == 1
    assert payload["changed_cells"][0]["before"] == "1.0"
    assert "S1" in capsys.readouterr().out


def test_cli_compare_quiet(capsys, tmp_path):
    from lims_dq.cli import main

    rows = [{"sample_id": "S1", "v": "1.0"}]
    a = _write_csv(tmp_path, "a.csv", rows)
    b = _write_csv(tmp_path, "b.csv", rows)
    assert main(["compare", a, b, "--key", "sample_id", "--quiet"]) == 0
    assert capsys.readouterr().out == ""


def test_cli_compare_max_diffs(capsys, tmp_path):
    from lims_dq.cli import main

    a = _write_csv(tmp_path, "a.csv", [{"sample_id": "S1", "v": "1.0"}])
    b = _write_csv(tmp_path, "b.csv", [{"sample_id": "S1", "v": "2.0"}])
    assert main(["compare", a, b, "--key", "sample_id", "--max-diffs", "1"]) == 0
    assert main(["compare", a, b, "--key", "sample_id", "--max-diffs", "0"]) == 1
    assert (
        main(["compare", a, b, "--key", "sample_id", "--max-diffs", "-1"]) == 2
    )


def test_cli_compare_tolerance(capsys, tmp_path):
    from lims_dq.cli import main

    a = _write_csv(tmp_path, "a.csv", [{"sample_id": "S1", "v": "0.10"}])
    b = _write_csv(tmp_path, "b.csv", [{"sample_id": "S1", "v": "0.1000001"}])
    assert main(["compare", a, b, "--key", "sample_id"]) == 1
    assert (
        main(["compare", a, b, "--key", "sample_id", "--tolerance", "0.001"]) == 0
    )


def test_cli_compare_missing_file(capsys, tmp_path):
    from lims_dq.cli import main

    assert main(["compare", "nope.csv", "also-nope.csv", "--key", "sample_id"]) == 2
    assert "not found" in capsys.readouterr().err


def test_cli_compare_duplicate_key_is_usage_error(capsys, tmp_path):
    from lims_dq.cli import main

    a = _write_csv(
        tmp_path,
        "a.csv",
        [{"sample_id": "S1", "v": "1.0"}, {"sample_id": "S1", "v": "2.0"}],
    )
    b = _write_csv(tmp_path, "b.csv", [{"sample_id": "S1", "v": "1.0"}])
    assert main(["compare", a, b, "--key", "sample_id"]) == 2
    assert "duplicate key" in capsys.readouterr().err


def test_cli_compare_missing_key_column(capsys, tmp_path):
    from lims_dq.cli import main

    rows = [{"sample_id": "S1", "v": "1.0"}]
    a = _write_csv(tmp_path, "a.csv", rows)
    b = _write_csv(tmp_path, "b.csv", rows)
    assert main(["compare", a, b, "--key", "wrong"]) == 2
    assert "key column" in capsys.readouterr().err
