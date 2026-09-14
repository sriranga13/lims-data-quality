"""Row-level diff of two data exports (migration / ETL parity checks).

A ``compare`` run answers the question "did anything change between this
LIMS export and the next one (or between the source extract and the
loaded target)?". Rows are aligned on a key column (e.g. ``sample_id``);
columns not present in both files are reported, and every differing cell
in matched rows is listed with its before/after values.

Numeric columns get a small tolerance (default 0): exports often round
floating point values (``0.10`` vs ``0.1``), and ``--tolerance 0.0001``
treats those as identical while still catching real data drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class ChangedCell:
    key: str
    column: str
    before: Any
    after: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "column": self.column,
            "before": self.before,
            "after": self.after,
        }


@dataclass
class ComparisonResult:
    """Outcome of comparing two data files."""

    before_name: str
    after_name: str
    key_column: str
    rows_before: int
    rows_after: int
    matched_rows: int
    identical_rows: int
    changed_rows: int
    only_in_before: list[str] = field(default_factory=list)
    only_in_after: list[str] = field(default_factory=list)
    columns_only_in_before: list[str] = field(default_factory=list)
    columns_only_in_after: list[str] = field(default_factory=list)
    changed_cells: list[ChangedCell] = field(default_factory=list)

    @property
    def identical(self) -> bool:
        """True when both files carry exactly the same rows, columns,
        and values."""
        return (
            not self.only_in_before
            and not self.only_in_after
            and not self.columns_only_in_before
            and not self.columns_only_in_after
            and not self.changed_cells
        )

    @property
    def diff_count(self) -> int:
        """Number of individual differences found."""
        return (
            len(self.only_in_before)
            + len(self.only_in_after)
            + len(self.columns_only_in_before)
            + len(self.columns_only_in_after)
            + len(self.changed_cells)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "before": self.before_name,
            "after": self.after_name,
            "key_column": self.key_column,
            "rows_before": self.rows_before,
            "rows_after": self.rows_after,
            "matched_rows": self.matched_rows,
            "identical_rows": self.identical_rows,
            "changed_rows": self.changed_rows,
            "only_in_before": self.only_in_before,
            "only_in_after": self.only_in_after,
            "columns_only_in_before": self.columns_only_in_before,
            "columns_only_in_after": self.columns_only_in_after,
            "changed_cells": [c.to_dict() for c in self.changed_cells],
            "identical": self.identical,
            "diff_count": self.diff_count,
        }

    def to_text(self) -> str:
        if self.identical:
            return (
                f"{self.before_name} and {self.after_name} are identical "
                f"({self.rows_before} rows, key column {self.key_column!r})"
            )
        lines = [
            f"differences between {self.before_name} and {self.after_name} "
            f"(key column {self.key_column!r}):"
        ]
        if self.only_in_before:
            lines.append(
                f"  rows only in {self.before_name}: "
                + ", ".join(self.only_in_before)
            )
        if self.only_in_after:
            lines.append(
                f"  rows only in {self.after_name}: "
                + ", ".join(self.only_in_after)
            )
        if self.columns_only_in_before:
            lines.append(
                "  columns only in "
                f"{self.before_name}: "
                + ", ".join(self.columns_only_in_before)
            )
        if self.columns_only_in_after:
            lines.append(
                "  columns only in "
                f"{self.after_name}: "
                + ", ".join(self.columns_only_in_after)
            )
        for cell in self.changed_cells:
            lines.append(
                f"  row {cell.key}: column {cell.column!r}: "
                f"{cell.before!r} -> {cell.after!r}"
            )
        lines.append(
            f"{self.diff_count} difference(s) across "
            f"{self.matched_rows} matched rows "
            f"({self.identical_rows} identical)"
        )
        return "\n".join(lines)


class CompareError(ValueError):
    """Raised when two files cannot be compared (bad key, dup keys, ...)."""


def _normalize(value: Any) -> str:
    """Compare-friendly string form: NaN and blanks both become ''."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _numerically_close(a: str, b: str, tolerance: float) -> bool | None:
    """True/False when both values are numeric, None otherwise."""
    if not a or not b:
        return None
    try:
        fa, fb = float(a), float(b)
    except (ValueError, OverflowError):
        return None
    return abs(fa - fb) <= tolerance


def _values_equal(a: Any, b: str, tolerance: float) -> bool:
    """Loose equality used for cell comparison."""
    na, nb = _normalize(a), _normalize(b)
    if na == nb:
        return True
    close = _numerically_close(na, nb, tolerance)
    return close if close is not None else False


def _index_by_key(df: pd.DataFrame, key: str, label: str) -> dict[str, pd.Series]:
    index: dict[str, pd.Series] = {}
    for _, record in df.iterrows():
        key_value = _normalize(record[key])
        if key_value in index:
            raise CompareError(
                f"duplicate key {key_value!r} in column {key!r} of {label}"
            )
        index[key_value] = record
    return index


def compare_dataframes(
    before: pd.DataFrame,
    after: pd.DataFrame,
    *,
    key: str,
    before_name: str = "before",
    after_name: str = "after",
    tolerance: float = 0.0,
) -> ComparisonResult:
    """Compare two DataFrames row by row, aligned on ``key``."""
    if tolerance < 0:
        raise CompareError("tolerance must be >= 0")
    for label, df in ((before_name, before), (after_name, after)):
        if key not in df.columns:
            raise CompareError(f"key column {key!r} not found in {label}")
        if df.empty:
            raise CompareError(f"cannot compare: {label} has no rows")

    before_index = _index_by_key(before, key, before_name)
    after_index = _index_by_key(after, key, after_name)

    result = ComparisonResult(
        before_name=before_name,
        after_name=after_name,
        key_column=key,
        rows_before=len(before),
        rows_after=len(after),
        matched_rows=0,
        identical_rows=0,
        changed_rows=0,
    )
    result.only_in_before = sorted(set(before_index) - set(after_index))
    result.only_in_after = sorted(set(after_index) - set(before_index))
    result.columns_only_in_before = sorted(
        set(before.columns) - set(after.columns)
    )
    result.columns_only_in_after = sorted(
        set(after.columns) - set(before.columns)
    )
    shared_columns = [c for c in before.columns if c in after.columns and c != key]

    for key_value in sorted(set(before_index) & set(after_index)):
        result.matched_rows += 1
        changed = False
        for column in shared_columns:
            b_val, a_val = before_index[key_value][column], after_index[key_value][column]
            if not _values_equal(b_val, a_val, tolerance):
                result.changed_cells.append(
                    ChangedCell(
                        key=key_value,
                        column=str(column),
                        before=None if _normalize(b_val) == "" else b_val,
                        after=None if _normalize(a_val) == "" else a_val,
                    )
                )
                changed = True
        if changed:
            result.changed_rows += 1
        else:
            result.identical_rows += 1
    return result
