"""Row-level validators: check a DataFrame against a RuleSet.

Every problem found becomes a :class:`ValidationError` carrying the
1-based data-row number (row 1 = first row beneath the header), the column
name, the offending value, the rule that failed, and a human message.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .schema import Rule, RuleSet
from .report import ValidationError


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def _check_dtype(rule: Rule, value: Any) -> str | None:
    """Return an error message if value violates rule.dtype, else None."""
    text = str(value).strip()
    if rule.dtype == "string":
        return None
    if rule.dtype == "int":
        try:
            if not float(text).is_integer():
                return f"{value!r} is not an integer"
        except (ValueError, OverflowError):
            return f"{value!r} is not an integer"
        return None
    if rule.dtype == "float":
        try:
            float(text)
        except (ValueError, OverflowError):
            return f"{value!r} is not a number"
        return None
    if rule.dtype == "date":
        if pd.to_datetime(text, errors="coerce") is pd.NaT:  # noqa: E711
            return f"{value!r} is not a recognizable date"
        return None
    return None  # unreachable: schema layer guards dtypes


def _check_constraints(rule: Rule, value: Any) -> list[str]:
    """Check pattern/min/max/allowed constraints; return error messages."""
    problems: list[str] = []
    text = str(value).strip()
    if rule.pattern is not None and not rule.matches_pattern(text):
        problems.append(f"{value!r} does not match pattern {rule.pattern!r}")
    if rule.dtype in ("int", "float"):
        number = float(text)  # safe: dtype check ran first
        if rule.min is not None and number < rule.min:
            problems.append(f"{value!r} is below minimum {rule.min}")
        if rule.max is not None and number > rule.max:
            problems.append(f"{value!r} is above maximum {rule.max}")
    if rule.allowed is not None and text not in rule.allowed:
        problems.append(f"{value!r} is not one of {list(rule.allowed)}")
    return problems


def validate_dataframe(
    df: pd.DataFrame, ruleset: RuleSet, *, strict: bool = True
) -> list[ValidationError]:
    """Validate every cell of ``df`` against ``ruleset``.

    ``strict=True`` (default) also flags columns present in the file but
    absent from the schema as ``unexpected_column`` errors.
    """
    errors: list[ValidationError] = []

    for name, rule in ruleset.rules.items():
        if rule.required and name not in df.columns:
            errors.append(
                ValidationError(
                    row=0,
                    column=name,
                    value=None,
                    rule="required_column",
                    message=f"required column {name!r} is missing from the file",
                )
            )

    if strict:
        for column in df.columns:
            if column not in ruleset.rules:
                errors.append(
                    ValidationError(
                        row=0,
                        column=str(column),
                        value=None,
                        rule="unexpected_column",
                        message=f"column {str(column)!r} is not defined in the schema",
                    )
                )

    for idx, (_, record) in enumerate(df.iterrows()):
        row_num = idx + 1  # 1-based data row
        for name, rule in ruleset.rules.items():
            if name not in df.columns:
                continue  # already reported as missing column
            value = record[name]
            if _is_missing(value):
                if rule.required:
                    errors.append(
                        ValidationError(
                            row=row_num,
                            column=name,
                            value=None,
                            rule="required",
                            message="required value is missing",
                        )
                    )
                continue
            dtype_problem = _check_dtype(rule, value)
            if dtype_problem is not None:
                errors.append(
                    ValidationError(
                        row=row_num,
                        column=name,
                        value=value if not pd.isna(value) else None,
                        rule="dtype",
                        message=dtype_problem,
                    )
                )
                continue  # skip constraint checks on wrongly-typed values
            for problem in _check_constraints(rule, value):
                errors.append(
                    ValidationError(
                        row=row_num,
                        column=name,
                        value=value if not pd.isna(value) else None,
                        rule="constraint",
                        message=problem,
                    )
                )
    return errors
