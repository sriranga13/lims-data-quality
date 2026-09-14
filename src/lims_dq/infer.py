"""Schema inference: generate a starter schema from a data file.

``lims-dq infer data.csv`` inspects the file and proposes a schema JSON
document. The result is a *starting point* -- tighten ranges, add ID
patterns and flip ``required`` flags before relying on it::

    lims-dq infer data.csv --out schema.json

Inference rules per column:

* ``required`` is true when the column has no missing values.
* ``dtype`` is the narrowest of ``int`` / ``float`` / ``date`` / ``string``
  that fits every non-missing value. Dates are only inferred when the
  column name hints at one (``date``, ``time``, ``_at``, ``_on`` ...),
  so numeric-looking strings are never misread as dates.
* Numeric columns get the observed ``min``/``max``.
* String columns with 2-10 distinct values get an ``allowed`` list.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .censored import parse_censored

_DATE_NAME_HINTS = ("date", "time", "datetime", "_at", "_on", "dob", "day")
_MAX_ALLOWED_DISTINCT = 10


def _present(series: pd.Series) -> list[str]:
    """Non-missing values of a column as stripped strings."""
    out: list[str] = []
    for value in series:
        if value is None:
            continue
        if isinstance(value, float) and pd.isna(value):
            continue
        text = str(value).strip()
        if text == "":
            continue
        out.append(text)
    return out


def _all_int(texts: list[str]) -> bool:
    if not texts:
        return False
    for text in texts:
        try:
            if not float(text).is_integer():
                return False
        except (ValueError, OverflowError):
            return False
    return True


def _all_float(texts: list[str]) -> bool:
    if not texts:
        return False
    for text in texts:
        try:
            float(text)
        except (ValueError, OverflowError):
            return False
    return True


def _float_or_censored(texts: list[str]) -> list[float] | None:
    """Numeric values if every text is a number or a censored value."""
    numbers: list[float] = []
    for text in texts:
        try:
            numbers.append(float(text))
            continue
        except (ValueError, OverflowError):
            pass
        if parse_censored(text) is None:
            return None
    return numbers or None


def _looks_like_date_column(name: str, texts: list[str]) -> bool:
    if not texts or not any(h in name.lower() for h in _DATE_NAME_HINTS):
        return False
    parsed = pd.to_datetime(texts, errors="coerce", format="mixed")
    hit_rate = int(parsed.notna().sum()) / len(texts)
    return hit_rate >= 0.9


def _infer_column(name: str, series: pd.Series) -> dict[str, Any]:
    texts = _present(series)
    spec: dict[str, Any] = {"required": len(texts) == len(series)}

    if _all_int(texts):
        numbers = [int(float(t)) for t in texts]
        spec["dtype"] = "int"
        spec["min"] = min(numbers)
        spec["max"] = max(numbers)
    elif _all_float(texts):
        numbers = [float(t) for t in texts]
        spec["dtype"] = "float"
        spec["min"] = min(numbers)
        spec["max"] = max(numbers)
    elif (mixed := _float_or_censored(texts)) is not None:
        # Numeric column with detection-limit values: keep it numeric and
        # opt in to censored values rather than degrading to string.
        spec["dtype"] = "float"
        spec["min"] = min(mixed)
        spec["max"] = max(mixed)
        spec["allow_censored"] = True
    elif _looks_like_date_column(name, texts):
        spec["dtype"] = "date"
    else:
        spec["dtype"] = "string"
        distinct = sorted(set(texts))
        # Categorical, not an identifier: values repeat and the set is small.
        if 2 <= len(distinct) <= _MAX_ALLOWED_DISTINCT and len(distinct) < len(texts):
            spec["allowed"] = distinct

    return spec


def infer_schema(
    df: pd.DataFrame, *, name: str = "inferred", version: str = "0.1.0"
) -> dict[str, Any]:
    """Infer a starter schema document from a DataFrame."""
    if df.empty:
        raise ValueError("cannot infer a schema from an empty file")
    columns = {str(col): _infer_column(str(col), df[col]) for col in df.columns}
    return {"name": name, "version": version, "columns": columns}
