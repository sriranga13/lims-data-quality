import hashlib
import json

from lims_dq.audit import build_entry, read_audit_log, sha256_of_file, write_audit_log


def test_sha256_matches_hashlib(tmp_path):
    path = tmp_path / "data.csv"
    path.write_bytes(b"sample_id\nSMP-000001\n")
    assert sha256_of_file(path) == hashlib.sha256(b"sample_id\nSMP-000001\n").hexdigest()


def test_build_entry_fields(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    entry = build_entry(
        filename=path,
        ruleset_name="lims-export",
        ruleset_version="1.0.0",
        rows_checked=10,
        rows_passed=9,
        rows_failed=1,
        error_count=2,
    )
    assert entry.filename == "data.csv"
    assert entry.ruleset_name == "lims-export"
    assert entry.ruleset_version == "1.0.0"
    assert entry.passed is False
    assert entry.timestamp_utc.endswith("+00:00")
    assert len(entry.file_sha256) == 64


def test_write_and_read_round_trip(tmp_path):
    log = tmp_path / "audit.jsonl"
    path = tmp_path / "data.csv"
    path.write_text("a\n1\n", encoding="utf-8")
    entry = build_entry(
        filename=path,
        ruleset_name="r",
        ruleset_version="0.1",
        rows_checked=1,
        rows_passed=1,
        rows_failed=0,
        error_count=0,
    )
    write_audit_log(entry, log)
    write_audit_log(entry, log)
    entries = read_audit_log(log)
    assert len(entries) == 2
    assert entries[0]["passed"] is True
    assert entries[0]["file_sha256"] == sha256_of_file(path)


def test_hash_changes_when_file_changes(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("a\n1\n", encoding="utf-8")
    before = sha256_of_file(path)
    path.write_text("a\n2\n", encoding="utf-8")
    assert sha256_of_file(path) != before


def test_each_entry_is_one_json_line(tmp_path):
    log = tmp_path / "audit.jsonl"
    path = tmp_path / "d.csv"
    path.write_text("a\n1\n", encoding="utf-8")
    entry = build_entry(
        filename=path, ruleset_name="r", ruleset_version="0.1",
        rows_checked=1, rows_passed=1, rows_failed=0, error_count=0,
    )
    write_audit_log(entry, log)
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    json.loads(lines[0])  # must parse as a single JSON document
