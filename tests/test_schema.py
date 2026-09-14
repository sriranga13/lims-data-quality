import json

import pytest

from lims_dq.schema import RuleSet, SchemaError, load_schema


def write_schema(tmp_path, doc):
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


VALID_DOC = {
    "name": "lims-export",
    "version": "2.3.1",
    "columns": {
        "sample_id": {
            "dtype": "string",
            "required": True,
            "pattern": "^SMP-[0-9]{6}$",
        },
        "concentration": {
            "dtype": "float",
            "required": True,
            "min": 0.0,
            "max": 100.0,
        },
        "unit": {
            "dtype": "string",
            "required": True,
            "allowed": ["mg/L", "ug/mL"],
        },
        "analyzed_at": {"dtype": "date", "required": False},
    },
}


def test_load_valid_schema(tmp_path):
    ruleset = load_schema(write_schema(tmp_path, VALID_DOC))
    assert isinstance(ruleset, RuleSet)
    assert ruleset.name == "lims-export"
    assert ruleset.version == "2.3.1"
    assert set(ruleset.rules) == {
        "sample_id",
        "concentration",
        "unit",
        "analyzed_at",
    }
    assert ruleset.required_columns() == ["sample_id", "concentration", "unit"]


def test_pattern_matching(tmp_path):
    ruleset = load_schema(write_schema(tmp_path, VALID_DOC))
    rule = ruleset.rules["sample_id"]
    assert rule.matches_pattern("SMP-000123")
    assert not rule.matches_pattern("SMP-123")
    assert not rule.matches_pattern("XYZ-000123")


def test_defaults_when_keys_absent(tmp_path):
    doc = {"columns": {"note": {}}}
    ruleset = load_schema(write_schema(tmp_path, doc))
    rule = ruleset.rules["note"]
    assert rule.dtype == "string"
    assert rule.required is False
    assert rule.pattern is None
    assert ruleset.version == "0.0.0"


def test_missing_file(tmp_path):
    with pytest.raises(SchemaError, match="not found"):
        load_schema(tmp_path / "nope.json")


def test_invalid_json(tmp_path):
    path = tmp_path / "schema.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SchemaError, match="not valid JSON"):
        load_schema(path)


def test_missing_columns_key(tmp_path):
    with pytest.raises(SchemaError, match="'columns'"):
        load_schema(write_schema(tmp_path, {"name": "x"}))


def test_unknown_dtype(tmp_path):
    doc = {"columns": {"c": {"dtype": "money"}}}
    with pytest.raises(SchemaError, match="unsupported dtype"):
        load_schema(write_schema(tmp_path, doc))


def test_unknown_keys_rejected(tmp_path):
    doc = {"columns": {"c": {"dtype": "string", "bogus": 1}}}
    with pytest.raises(SchemaError, match="unknown keys"):
        load_schema(write_schema(tmp_path, doc))


def test_bad_regex(tmp_path):
    doc = {"columns": {"c": {"pattern": "([a-z"}}}
    with pytest.raises(SchemaError, match="invalid regex"):
        load_schema(write_schema(tmp_path, doc))


def test_min_greater_than_max(tmp_path):
    doc = {"columns": {"c": {"dtype": "float", "min": 10, "max": 5}}}
    with pytest.raises(SchemaError, match="min.*> max"):
        load_schema(write_schema(tmp_path, doc))


def test_min_max_on_string_rejected(tmp_path):
    doc = {"columns": {"c": {"dtype": "string", "min": 0}}}
    with pytest.raises(SchemaError, match="min/max only apply"):
        load_schema(write_schema(tmp_path, doc))


def test_allowed_must_be_nonempty_list(tmp_path):
    doc = {"columns": {"c": {"allowed": []}}}
    with pytest.raises(SchemaError, match="'allowed' must be a non-empty list"):
        load_schema(write_schema(tmp_path, doc))
