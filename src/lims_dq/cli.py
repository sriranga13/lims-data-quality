"""Command-line interface: ``lims-dq validate data.csv --schema schema.json``.

Exit codes: 0 = all rows pass, 1 = validation failures found,
2 = usage or file errors (missing file, bad schema, unreadable data).
``--max-errors N`` tolerates up to N errors and still exits 0.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from . import __version__
from .audit import build_entry, write_audit_log
from .censored import collect_censored
from .compare import CompareError, compare_dataframes
from .infer import infer_schema
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
    validate.add_argument(
        "--max-errors",
        type=int,
        default=None,
        metavar="N",
        help="Exit 0 if the error count is at most N (for CI pipelines "
        "that tolerate a few bad rows)",
    )
    validate.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the console report; the exit code (and --report / "
        "--audit-log files, if given) still carry the result",
    )

    infer = sub.add_parser(
        "infer", help="Generate a starter schema from a data file."
    )
    infer.add_argument("data_file", help="CSV or Excel file to inspect")
    infer.add_argument(
        "--out",
        default=None,
        help="Write the schema JSON to this path (default: print to stdout)",
    )
    infer.add_argument(
        "--name", default="inferred", help="Schema name (default: inferred)"
    )

    compare = sub.add_parser(
        "compare", help="Row-level diff of two data exports (migration/ETL parity)."
    )
    compare.add_argument("before_file", help="Baseline CSV or Excel file")
    compare.add_argument("after_file", help="New CSV or Excel file")
    compare.add_argument(
        "--key",
        required=True,
        help="Column used to align rows (e.g. sample_id)",
    )
    compare.add_argument(
        "--report",
        default=None,
        help="Write the comparison as JSON to this path",
    )
    compare.add_argument(
        "--tolerance",
        type=float,
        default=0.0,
        help="Numeric tolerance for cell comparison (default: 0)",
    )
    compare.add_argument(
        "--max-diffs",
        type=int,
        default=None,
        metavar="N",
        help="Exit 0 if the difference count is at most N",
    )
    compare.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the console report; the exit code (and --report, "
        "if given) still carries the result",
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
    censored = collect_censored(df, ruleset)
    report = ErrorReport(
        filename=data_path.name,
        ruleset_name=ruleset.name,
        ruleset_version=ruleset.version,
        rows_checked=len(df),
        errors=errors,
        censored=censored,
    )
    if not args.quiet:
        print(report.to_text())

    if args.report:
        Path(args.report).write_text(report.to_json() + "\n", encoding="utf-8")
        if not args.quiet:
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
        if not args.quiet:
            print(f"audit entry appended to {args.audit_log}")

    if args.max_errors is not None:
        if args.max_errors < 0:
            print("error: --max-errors must be >= 0", file=sys.stderr)
            return 2
        return 0 if len(errors) <= args.max_errors else 1
    return 0 if report.passed else 1


def cmd_infer(args: argparse.Namespace) -> int:
    data_path = Path(args.data_file)
    if not data_path.is_file():
        print(f"error: data file not found: {data_path}", file=sys.stderr)
        return 2
    try:
        df = load_data_file(data_path)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # unreadable file, bad encoding, ...
        print(f"error: could not read {data_path}: {exc}", file=sys.stderr)
        return 2
    try:
        document = infer_schema(df, name=args.name)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    text = json.dumps(document, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"schema written to {args.out} -- review and tighten it before use")
    else:
        print(text, end="")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    """Diff two exports row by row. Exit 0 = identical, 1 = differences,
    2 = usage or file errors. ``--max-diffs N`` tolerates up to N diffs."""
    before_path = Path(args.before_file)
    after_path = Path(args.after_file)
    for path in (before_path, after_path):
        if not path.is_file():
            print(f"error: data file not found: {path}", file=sys.stderr)
            return 2
    if args.tolerance < 0:
        print("error: --tolerance must be >= 0", file=sys.stderr)
        return 2
    try:
        before_df = load_data_file(before_path)
        after_df = load_data_file(after_path)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # unreadable file, bad encoding, ...
        print(f"error: could not read input: {exc}", file=sys.stderr)
        return 2
    try:
        result = compare_dataframes(
            before_df,
            after_df,
            key=args.key,
            before_name=before_path.name,
            after_name=after_path.name,
            tolerance=args.tolerance,
        )
    except CompareError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not args.quiet:
        print(result.to_text())
    if args.report:
        Path(args.report).write_text(
            json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8"
        )
        if not args.quiet:
            print(f"\ncomparison written to {args.report}")

    if args.max_diffs is not None:
        if args.max_diffs < 0:
            print("error: --max-diffs must be >= 0", file=sys.stderr)
            return 2
        return 0 if result.diff_count <= args.max_diffs else 1
    return 0 if result.identical else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "validate":
        return cmd_validate(args)
    if args.command == "infer":
        return cmd_infer(args)
    if args.command == "compare":
        return cmd_compare(args)
    parser.error(f"unknown command {args.command!r}")
    return 2  # unreachable


if __name__ == "__main__":
    sys.exit(main())
