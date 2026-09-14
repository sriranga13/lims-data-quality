"""Command-line interface: ``lims-dq validate data.csv --schema schema.json``.

Exit codes: 0 = all rows pass, 1 = validation failures found,
2 = usage or file errors (missing file, bad schema, unreadable data).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from . import __version__
from .audit import build_entry, write_audit_log
from .report import ErrorReport
from .schema import SchemaError, load_schema
from .validators import validate_dataframe

SUPPORTED_SUFFIXES = {".csv", ".xlsx", ".xls"}


def load_data_file(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, dtype=str)
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(path, dtype=str)
    raise ValueError(
        f"unsupported file type {path.suffix!r} "
        f"(expected one of {sorted(SUPPORTED_SUFFIXES)})"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lims-dq",
        description="Validate lab/LIMS data files against a schema before they "
        "enter your pipeline.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser(
        "validate", help="Validate a data file against a schema."
    )
    validate.add_argument("data_file", help="CSV or Excel file to validate")
    validate.add_argument(
        "--schema", required=True, help="Path to the schema JSON file"
    )
    validate.add_argument(
        "--report",
        default=None,
        help="Write the full error report as JSON to this path",
    )
    validate.add_argument(
        "--audit-log",
        default=None,
        help="Append a JSON-lines audit entry to this log file",
    )
    validate.add_argument(
        "--no-strict",
        action="store_true",
        help="Do not flag columns missing from the schema",
    )
    return parser


def cmd_validate(args: argparse.Namespace) -> int:
    data_path = Path(args.data_file)
    if not data_path.is_file():
        print(f"error: data file not found: {data_path}", file=sys.stderr)
        return 2
    try:
        ruleset = load_schema(args.schema)
    except SchemaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        df = load_data_file(data_path)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # unreadable file, bad encoding, ...
        print(f"error: could not read {data_path}: {exc}", file=sys.stderr)
        return 2

    errors = validate_dataframe(df, ruleset, strict=not args.no_strict)
    report = ErrorReport(
        filename=data_path.name,
        ruleset_name=ruleset.name,
        ruleset_version=ruleset.version,
        rows_checked=len(df),
        errors=errors,
    )
    print(report.to_text())

    if args.report:
        Path(args.report).write_text(report.to_json() + "\n", encoding="utf-8")
        print(f"\nJSON report written to {args.report}")

    if args.audit_log:
        entry = build_entry(
            filename=data_path,
            ruleset_name=ruleset.name,
            ruleset_version=ruleset.version,
            rows_checked=report.rows_checked,
            rows_passed=report.rows_passed,
            rows_failed=report.rows_failed,
            error_count=len(errors),
        )
        write_audit_log(entry, args.audit_log)
        print(f"audit entry appended to {args.audit_log}")

    return 0 if report.passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "validate":
        return cmd_validate(args)
    parser.error(f"unknown command {args.command!r}")
    return 2  # unreachable


if __name__ == "__main__":
    sys.exit(main())
