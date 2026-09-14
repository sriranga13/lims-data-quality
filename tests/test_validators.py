import pandas as pd
import pytest

from lims_dq.report import ValidationError
from lims_dq.schema import Rule, RuleSet
from lims_dq.validators import validate_dataframe


def make_ruleset(**overrides):
    rules = {
        "sample_id": Rule(
            name="sample_id", dtype="string", required=True,
            pattern="^SMP-[0-9]{6}$",
        ).compile(),
        "concentration": Rule(
            name="concentration", dtype="float", required=True, min=0.0, max=100.0
        ),
        "unit": Rule(
            name="unit", dtype="string", required=True,
            allowed=("mg/L", "ug/mL"),
        ),
        "replicates": Rule(name="replicates", dtype="int", required=False),
    }
    rules.update(overrides)
    return RuleSet(name="t", version="1.0", rules=rules)


def good_df():
    return pd.DataFrame(
        {
            "sample_id": ["SMP-000001", "SMP-000002"],
            "concentration": ["12.5", "0.0"],
            "unit": ["mg/L", "ug/mL"],
            "replicates": ["3", ""],
        }
    )


def errors_by(df, ruleset, **kwargs):
    return {(e.row, e.column, e.rule): e for e in validate_dataframe(df, ruleset, **kwargs)}


def test_happy_path():
    assert validate_dataframe(good_df(), make_ruleset()) == []


def test_missing_required_column():
    df = good_df().drop(columns=["unit"])
    errs = errors_by(df, make_ruleset())
    assert (0, "unit", "required_column") in errs


def test_unexpected_column_strict():
    df = good_df().copy()
    df["surprise"] = "x"
    errs = errors_by(df, make_ruleset())
    assert (0, "surprise", "unexpected_column") in errs


def test_unexpected_column_not_strict():
    df = good_df().copy()
    df["surprise"] = "x"
    assert validate_dataframe(df, make_ruleset(), strict=False) == []


def test_missing_required_value():
    df = good_df()
    df.loc[1, "concentration"] = None
    errs = errors_by(df, make_ruleset())
    assert (2, "concentration", "required") in errs


def test_optional_missing_value_ok():
    df = good_df()
    df.loc[0, "replicates"] = None  # optional column
    assert validate_dataframe(df, make_ruleset()) == []


def test_pattern_violation():
    df = good_df()
    df.loc[0, "sample_id"] = "BAD-ID"
    errs = errors_by(df, make_ruleset())
    key = (1, "sample_id", "constraint")
    assert key in errs
    assert "pattern" in errs[key].message


def test_float_dtype_violation():
    df = good_df()
    df.loc[1, "concentration"] = "twelve"
    errs = errors_by(df, make_ruleset())
    assert (2, "concentration", "dtype") in errs


def test_range_violations():
    df = good_df()
    df.loc[0, "concentration"] = "-1"
    df.loc[1, "concentration"] = "101"
    errs = errors_by(df, make_ruleset())
    assert (1, "concentration", "constraint") in errs
    assert "minimum" in errs[(1, "concentration", "constraint")].message
    assert "maximum" in errs[(2, "concentration", "constraint")].message


def test_allowed_values_violation():
    df = good_df()
    df.loc[0, "unit"] = "kg"
    errs = errors_by(df, make_ruleset())
    assert (1, "unit", "constraint") in errs


def test_int_dtype():
    df = good_df()
    df.loc[0, "replicates"] = "2.5"
    errs = errors_by(df, make_ruleset())
    assert (1, "replicates", "dtype") in errs
    df.loc[0, "replicates"] = "4"  # integral string is fine
    assert (1, "replicates", "dtype") not in errors_by(df, make_ruleset())


def test_date_dtype():
    ruleset = RuleSet(
        name="t",
        version="1.0",
        rules={"analyzed_at": Rule(name="analyzed_at", dtype="date")},
    )
    ok = pd.DataFrame({"analyzed_at": ["2026-09-01", "09/02/2026"]})
    assert validate_dataframe(ok, ruleset) == []
    bad = pd.DataFrame({"analyzed_at": ["not a date"]})
    errs = errors_by(bad, ruleset)
    assert (1, "analyzed_at", "dtype") in errs


def test_row_numbering_is_one_based():
    df = good_df()
    df.loc[1, "unit"] = "wrong"
    (err,) = [e for e in validate_dataframe(df, make_ruleset()) if e.rule == "constraint"]
    assert isinstance(err, ValidationError)
    assert err.row == 2
    assert err.column == "unit"
