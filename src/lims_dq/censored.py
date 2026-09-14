"""Detection-limit ("censored") values common in lab data.

Instruments and LIMS exports routinely report values like ``<0.01``,
``ND`` (not detected), ``BQL`` (below quantification limit) or ``TNTC``
(too numerous to count) in numeric columns. These are *not* malformed
data -- they are meaningful results -- so a schema column can opt in to
accepting them with ``"allow_censored": true``::

    {"concentration": {"dtype": "float", "required": True,
                       "allow_censored": True}}

Accepted values are recorded as :class:`CensoredHit` so reports and audit
trails can show how many results were censored and why.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

_LIMIT_RE = re.compile(
    r"^\s*(<=?|>=?)\s*([0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)\s*$"
)

# Qualifier tokens (case-insensitive) mapped to a canonical kind.
_TOKENS = {
    "nd": "not_detected",
    "n.d.": "not_detected",
    "not detected": "not_detected",
    "bql": "below",
    "bloq": "below",
    "<loq": "below",
    "below loq": "below",
    "lod": "below",
    "<lod": "below",
    "aql": "above",
    "aloq": "above",
    ">loq": "above",
    "tftc": "too_numerous",
    "tntc": "too_numerous",
    "too numerous to count": "too_numerous",
}


@dataclass
class CensoredValue:
    """A parsed detection-limit value.

    ``kind`` is one of ``"below"``, ``"above"``, ``"not_detected"`` or
    ``"too_numerous"``; ``limit`` is the numeric threshold when one was
    given (e.g. ``0.01`` for ``"<0.01"``), else ``None``.
    """

    kind: str
    limit: float | None
    raw: str


@dataclass
class CensoredHit:
    """One accepted censored value, for reports and audit trails."""

    row: int  # 1-based data-row number
    column: str
    value: Any
    kind: str
    limit: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "column": self.column,
            "value": None if self.value is None or pd.isna(self.value) else str(self.value),
            "kind": self.kind,
            "limit": self.limit,
        }


def parse_censored(value: Any) -> CensoredValue | None:
    """Parse a detection-limit value; return None if it isn't one."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    lowered = text.lower()
    if lowered in _TOKENS:
        return CensoredValue(kind=_TOKENS[lowered], limit=None, raw=text)

    match = _LIMIT_RE.match(text)
    if match:
        operator, number = match.group(1), float(match.group(2))
        kind = "below" if operator.startswith("<") else "above"
        return CensoredValue(kind=kind, limit=number, raw=text)

    return None


def collect_censored(
    df: pd.DataFrame, ruleset: "RuleSet"
) -> list[CensoredHit]:
    """Find accepted censored values in columns with ``allow_censored``."""
    from .schema import RuleSet  # local import: schema never imports censored

    assert isinstance(ruleset, RuleSet)
    hits: list[CensoredHit] = []
    for name, rule in ruleset.rules.items():
        if rule.dtype not in ("int", "float") or not rule.allow_censored:
            continue
        if name not in df.columns:
            continue
        for idx, value in enumerate(df[name]):
            if value is None or (isinstance(value, float) and pd.isna(value)):
                continue
            if isinstance(value, str) and value.strip() == "":
                continue
            parsed = parse_censored(value)
            if parsed is not None:
                hits.append(
                    CensoredHit(
                        row=idx + 1,
                        column=name,
                        value=value,
                        kind=parsed.kind,
                        limit=parsed.limit,
                    )
                )
    return hits
