"""Minimal audit trail: who validated what, when, against which rules.

Each validation run appends one JSON-lines entry recording the UTC
timestamp, the SHA-256 hash of the input file, the rule set name and
version, and the pass/fail counts. The file hash makes the entry
tamper-evident: re-running against a modified file produces a different
hash. A nod to 21 CFR Part 11 style traceability — not a compliance
certification.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class AuditEntry:
    timestamp_utc: str
    filename: str
    file_sha256: str
    ruleset_name: str
    ruleset_version: str
    rows_checked: int
    rows_passed: int
    rows_failed: int
    error_count: int
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sha256_of_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_entry(
    *,
    filename: str | Path,
    ruleset_name: str,
    ruleset_version: str,
    rows_checked: int,
    rows_passed: int,
    rows_failed: int,
    error_count: int,
) -> AuditEntry:
    path = Path(filename)
    return AuditEntry(
        timestamp_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        filename=path.name,
        file_sha256=sha256_of_file(path),
        ruleset_name=ruleset_name,
        ruleset_version=ruleset_version,
        rows_checked=rows_checked,
        rows_passed=rows_passed,
        rows_failed=rows_failed,
        error_count=error_count,
        passed=error_count == 0,
    )


def write_audit_log(entry: AuditEntry, log_path: str | Path) -> None:
    """Append one entry (as a single JSON line) to the audit log."""
    log_path = Path(log_path)
    if log_path.parent != Path("."):
        log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry.to_dict()) + "\n")


def read_audit_log(log_path: str | Path) -> list[dict[str, Any]]:
    """Read all entries from a JSON-lines audit log."""
    entries = []
    with open(log_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries
