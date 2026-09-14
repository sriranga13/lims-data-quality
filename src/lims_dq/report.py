"""Row-level error reports: console text and JSON."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ValidationError:
    """A single failed check.

    ``row`` is the 1-based data-row number (row 1 = first row under the
    header); ``row=0`` means the problem is file-level (e.g. a missing
    column) rather than tied to a data row.
    """

    row: int
    column: str
    value: Any
    rule: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ErrorReport:
    """Aggregated result of validating one file."""

    filename: str
    ruleset_name: str
    ruleset_version: str
    rows_checked: int
    errors: list[ValidationError]

    @property
    def passed(self) -> bool:
        return not self.errors

    @property
    def rows_failed(self) -> int:
        return len({e.row for e in self.errors if e.row > 0})

    @property
    def rows_passed(self) -> int:
        return self.rows_checked - self.rows_failed

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "ruleset": {"name": self.ruleset_name, "version": self.ruleset_version},
            "summary": {
                "passed": self.passed,
                "rows_checked": self.rows_checked,
                "rows_passed": self.rows_passed,
                "rows_failed": self.rows_failed,
                "error_count": len(self.errors),
                "errors_by_rule": dict(Counter(e.rule for e in self.errors)),
                "errors_by_column": dict(Counter(e.column for e in self.errors)),
            },
            "errors": [e.to_dict() for e in self.errors],
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def to_text(self) -> str:
        lines = [
            f"lims-dq report: {self.filename}",
            f"ruleset: {self.ruleset_name} v{self.ruleset_version}",
            f"rows checked: {self.rows_checked} | "
            f"passed: {self.rows_passed} | failed: {self.rows_failed} | "
            f"errors: {len(self.errors)}",
        ]
        if self.passed:
            lines.append("PASS: all rows satisfy the schema.")
            return "\n".join(lines)
        lines.append("")
        lines.append(f"{'row':>5}  {'column':<18} {'rule':<18} message")
        lines.append("-" * 72)
        for e in self.errors:
            row = "file" if e.row == 0 else str(e.row)
            lines.append(f"{row:>5}  {e.column:<18} {e.rule:<18} {e.message}")
        return "\n".join(lines)
