import json

import pandas as pd
import pytest

from lims_dq.infer import infer_schema
from lims_dq.schema import SchemaError, load_schema


def make_df():
    return pd.DataFrame(
        {
            "sample_id": ["SMP-000001", "SMP-000002", "SMP-000003"],
            "concentration": ["12.5", "0.75", "45.0"],
            "replicates": ["3", "2", "1"],
            "unit": ["mg/L", "ug/mL", "mg/L"],
            "analyzed_at": ["2026-09-01", "2026-09-02", "2026-09-03"],
            "notes": ["ok", "", "rerun"],
        }
    )


def test_infer_dtypes():
    doc = infer_schema(make_df(), name="lab")
    cols = doc["columns"]
    assert cols["sample_id"]["dtype"] == "string"
    assert cols["concentration"]["dtype"] == "float"
    assert cols["replicates"]["dtype"] == "int"
    assert cols["analyzed_at"]["dtype"] == "date"


def test_infer_required_flags():
    cols = infer_schema(make_df())["columns"]
    assert cols["sample_id"]["required"] is True
    assert cols["notes"]["required"] is False  # has a blank


def test_infer_numeric_ranges():
    cols = infer_schema(make_df())["columns"]
    assert cols["concentration"]["min"] == 0.75
    assert cols["concentration"]["max"] == 45.0
    assert cols["replicates"]["min"] == 1
    assert cols["replicates"]["max"] == 3


def test_infer_allowed_for_low_cardinality_strings():
    cols = infer_schema(make_df())["columns"]
    assert cols["unit"]["allowed"] == ["mg/L", "ug/mL"]
    assert "allowed" not in cols["sample_id"]  # every value unique


def test_inferred_schema_loads(tmp_path):
    doc = infer_schema(make_df(), name="lab")
    path = tmp_path / "inferred.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    ruleset = load_schema(path)  # must be a valid schema document
    assert ruleset.name == "lab"
    assert set(ruleset.rules) == set(make_df().columns)


def test_infer_empty_frame_raises():
    with pytest.raises(ValueError):
        infer_schema(pd.DataFrame({"a": []}))


def test_date_needs_name_hint():
    # Numeric-looking values in a column without a date-ish name stay numeric.
    df = pd.DataFrame({"code": ["20260101", "20260202"]})
    assert infer_schema(df)["columns"]["code"]["dtype"] == "int"


def test_high_cardinality_strings_have_no_allowed():
    df = pd.DataFrame({"id": [f"X-{i:04d}" for i in range(50)]})
    assert "allowed" not in infer_schema(df)["columns"]["id"]


def test_schema_rejects_allow_censored_on_string(tmp_path):
    bad = {
        "name": "x",
        "version": "1",
        "columns": {"s": {"dtype": "string", "allow_censored": True}},
    }
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(SchemaError):
        load_schema(path)


def test_schema_accepts_allow_censored_on_float(tmp_path):
    good = {
        "name": "x",
        "version": "1",
        "columns": {"c": {"dtype": "float", "allow_censored": True}},
    }
    path = tmp_path / "good.json"
    path.write_text(json.dumps(good), encoding="utf-8")
    assert load_schema(path).rules["c"].allow_censored is True


def test_infer_detects_censored_numeric_column():
    df = pd.DataFrame({"conc": ["12.5", "<0.01", "ND", "3.0"]})
    col = infer_schema(df)["columns"]["conc"]
    assert col["dtype"] == "float"
    assert col["allow_censored"] is True
    assert col["min"] == 3.0
    assert col["max"] == 12.5


def test_infer_censored_schema_validates():
    import pandas as pd

    from lims_dq.censored import collect_censored
    from lims_dq.validators import validate_dataframe

    df = pd.DataFrame({"conc": ["12.5", "<0.01", "ND"]})
    ruleset = load_schema_from_doc(infer_schema(df))
    assert validate_dataframe(df, ruleset, strict=False) == []
    assert len(collect_censored(df, ruleset)) == 2


def load_schema_from_doc(doc):
    import json
    import tempfile
    from pathlib import Path

    path = Path(tempfile.mkdtemp()) / "s.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return load_schema(path)
