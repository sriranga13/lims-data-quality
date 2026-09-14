"""Schema loading and validation for lims-dq.

A schema is a JSON document describing the columns a data file must have::

    {
        "name": "lims-export",
        "version": "1.0.0",
        "columns": {
            "sample_id":     {"dtype": "string", "required": true,
                              "pattern": "^SMP-[0-9]{6}$"},
            "concentration": {"dtype": "float", "required": true,
                              "min": 0.0, "max": 100.0},
            "unit":          {"dtype": "string", "required": true,
                              "allowed": ["mg/L", "ug/mL", "ng/uL"]},
            "analyzed_at":   {"dtype": "date", "required": false}
        }
    }

Supported dtypes: ``string``, ``int``, ``float``, ``date``.
Supported constraints: ``required``, ``pattern`` (regex, full match),
``min``/``max`` (numeric dtypes only), ``allowed`` (enumerated values),
``allow_censored`` (accept detection-limit values like ``<0.01`` or
``ND`` in numeric columns; see :mod:`lims_dq.censored`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SUPPORTED_DTYPES = ("string", "int", "float", "date")


class SchemaError(ValueError):
    """Raised when a schema document is malformed."""


@dataclass
class Rule:
    """Validation rule for a single column."""

    name: str
    dtype: str = "string"
    required: bool = False
    pattern: str | None = None
    min: float | None = None
    max: float | None = None
    allowed: tuple[str, ...] | None = None
    allow_censored: bool = False
    _regex: re.Pattern | None = field(default=None, repr=False, compare=False)

    def compile(self) -> "Rule":
        if self.pattern is not None:
            try:
                self._regex = re.compile(self.pattern)
            except re.error as exc:
                raise SchemaError(
                    f"column {self.name!r}: invalid regex {self.pattern!r}: {exc}"
                ) from exc
        return self

    def matches_pattern(self, value: str) -> bool:
        assert self._regex is not None
        return self._regex.fullmatch(value) is not None


@dataclass
class RuleSet:
    """A named, versioned collection of column rules."""

    name: str
    version: str
    rules: dict[str, Rule]

    def required_columns(self) -> list[str]:
        return [n for n, r in self.rules.items() if r.required]


def _coerce_rule(name: str, spec: Any) -> Rule:
    if not isinstance(spec, dict):
        raise SchemaError(f"column {name!r}: rule must be an object, got {type(spec).__name__}")
    dtype = spec.get("dtype", "string")
    if dtype not in SUPPORTED_DTYPES:
        raise SchemaError(
            f"column {name!r}: unsupported dtype {dtype!r} "
            f"(expected one of {SUPPORTED_DTYPES})"
        )
    unknown = set(spec) - {
        "dtype", "required", "pattern", "min", "max", "allowed", "allow_censored"
    }
    if unknown:
        raise SchemaError(f"column {name!r}: unknown keys {sorted(unknown)}")

    allow_censored = bool(spec.get("allow_censored", False))
    if allow_censored and dtype not in ("int", "float"):
        raise SchemaError(
            f"column {name!r}: allow_censored only applies to int/float dtypes"
        )

    min_v = spec.get("min")
    max_v = spec.get("max")
    if (min_v is not None or max_v is not None) and dtype not in ("int", "float"):
        raise SchemaError(f"column {name!r}: min/max only apply to int/float dtypes")
    if min_v is not None and max_v is not None and min_v > max_v:
        raise SchemaError(f"column {name!r}: min ({min_v}) > max ({max_v})")

    allowed = spec.get("allowed")
    if allowed is not None:
        if not isinstance(allowed, list) or not allowed:
            raise SchemaError(f"column {name!r}: 'allowed' must be a non-empty list")
        allowed = tuple(str(v) for v in allowed)

    return Rule(
        name=name,
        dtype=dtype,
        required=bool(spec.get("required", False)),
        pattern=spec.get("pattern"),
        min=min_v,
        max=max_v,
        allowed=allowed,
        allow_censored=allow_censored,
    ).compile()


def load_schema(path: str | Path) -> RuleSet:
    """Load and validate a schema JSON file, returning a RuleSet."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SchemaError(f"schema file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise SchemaError(f"schema file {path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise SchemaError("schema must be a JSON object")
    columns = raw.get("columns")
    if not isinstance(columns, dict) or not columns:
        raise SchemaError("schema must define a non-empty 'columns' object")
    rules = {name: _coerce_rule(name, spec) for name, spec in columns.items()}
    return RuleSet(
        name=str(raw.get("name", path.stem)),
        version=str(raw.get("version", "0.0.0")),
        rules=rules,
    )
