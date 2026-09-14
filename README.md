[![PyPI](https://img.shields.io/pypi/v/lims-data-quality.svg)](https://pypi.org/project/lims-data-quality/)
# lims-data-quality

Validate lab/LIMS data files before they hit your pipeline — schema checks, row-level error reports, audit trails.

`lims-dq` checks CSV/Excel exports against a JSON schema (required columns, dtypes, ranges, regex ID patterns, allowed values) and tells you exactly which row, which column, and why it failed. Every run can append a tamper-evident audit entry (timestamp, file hash, rule set version, pass/fail counts) — a nod to 21 CFR Part 11 style traceability.

## Install

```bash
pip install lims-data-quality
```

Or from source:

```bash
git clone https://github.com/sriranga13/lims-data-quality.git
cd lims-data-quality
pip install -e .
```

Requires Python 3.10+.

## Quickstart

1. Describe your file with a schema (`schema.json`):

```json
{
  "name": "lims-export",
  "version": "1.0.0",
  "columns": {
    "sample_id":     { "dtype": "string", "required": true, "pattern": "^SMP-[0-9]{6}$" },
    "concentration": { "dtype": "float",  "required": true, "min": 0.0, "max": 100.0 },
    "unit":          { "dtype": "string", "required": true, "allowed": ["mg/L", "ug/mL", "ng/uL"] },
    "analyzed_at":   { "dtype": "date",   "required": false },
    "replicates":    { "dtype": "int",    "required": false, "min": 1, "max": 12 }
  }
}
```

2. Validate:

```bash
lims-dq validate samples.csv --schema schema.json
```

Sample output:

```
lims-dq report: samples.csv
ruleset: lims-export v1.0.0
rows checked: 5 | passed: 3 | failed: 2 | errors: 7

  row  column             rule               message
------------------------------------------------------------------------
    4  analyzed_at        dtype              'not-a-date' is not a recognizable date
    4  concentration      constraint         '150.0' is above maximum 100.0
    4  replicates         constraint         '0' is below minimum 1
    4  sample_id          constraint         'BAD-ID' does not match pattern '^SMP-[0-9]{6}$'
    4  unit               constraint         'kg' is not one of ['mg/L', 'ug/mL', 'ng/uL']
    5  concentration      required           required value is missing
    5  replicates         constraint         '13' is above maximum 12
```

3. Machine-readable report and audit trail:

```bash
lims-dq validate samples.csv --schema schema.json \
    --report report.json \
    --audit-log audit.jsonl
```

- `--report` writes the full report (summary counts + every error) as JSON.
- `--audit-log` appends one JSON-lines entry per run: UTC timestamp, SHA-256 of the input file, rule set name/version, rows checked/passed/failed, error count. Re-running against a modified file produces a different hash, so entries are tamper-evident.

Exit codes: `0` = all rows pass, `1` = validation failures, `2` = usage/file errors.

## Generate a starter schema

Don't want to hand-write `schema.json`? Infer one from the data:

```bash
lims-dq infer samples.csv --out schema.json
```

This inspects each column and proposes dtypes, required flags, observed min/max, and allowed-value lists for categorical columns. Columns that mix numbers with detection-limit values (see below) are inferred as numeric with `allow_censored` already set. **Always review and tighten the result** — inferred ranges describe your sample, not your spec.

## Detection-limit values

Lab exports are full of `<0.01`, `ND`, `BQL`, `TNTC` — meaningful results, not malformed data. Opt a numeric column in:

```json
{ "concentration": { "dtype": "float", "required": true, "allow_censored": true } }
```

Censored values then pass validation and are counted in the report (`censored values accepted: N`, with per-row detail in `--report` JSON) instead of failing as "not a number". Recognized forms: `<`, `<=`, `>`, `>=` thresholds and the qualifiers ND, BQL/BLOQ, AQL/ALOQ, LOD, TNTC/TFTC.

## CI mode and GitHub Action

Gate your pipeline on data quality. Tolerate a few bad rows without failing the build:

```bash
lims-dq validate drop.csv --schema schema.json --max-errors 5 --quiet
```

- `--max-errors N` exits 0 when the error count is at most N.
- `--quiet` suppresses console output (the exit code and any `--report`/`--audit-log` files still carry the result).

Or drop it into GitHub Actions with the bundled `action.yml`:

```yaml
- uses: sriranga13/lims-data-quality@v0.2.0
  with:
    data-file: data/drop.csv
    schema: schemas/drop.json
    max-errors: "5"
    report: report.json
```

## Compare two exports

Moving to a new LIMS, or checking that a loaded table matches the source extract? Diff two files row by row, aligned on a key column:

```bash
lims-dq compare migration_before.csv migration_after.csv --key sample_id
```

Sample output:

```
differences between migration_before.csv and migration_after.csv (key column 'sample_id'):
  rows only in migration_before.csv: SMP-000003
  rows only in migration_after.csv: SMP-000004
  row SMP-000002: column 'concentration': '0.10' -> '0.1000001'
3 difference(s) across 2 matched rows (1 identical)
```

- `--tolerance` treats tiny numeric drift (rounding between systems) as identical: `--tolerance 0.001` makes `0.10` and `0.1000001` match.
- Duplicate keys in either file are rejected (exit 2): a key must identify one row.
- `--report` writes the full diff as JSON; `--max-diffs N` tolerates up to N differences; `--quiet` suppresses console output.

Exit codes: `0` = identical, `1` = differences found, `2` = usage/file errors.

## Schema reference

| Key        | Applies to        | Meaning                                          |
|------------|-------------------|--------------------------------------------------|
| `dtype`    | all               | `string`, `int`, `float`, or `date`              |
| `required` | all               | missing values fail (missing column fails too)   |
| `pattern`  | all               | regex the full value must match                  |
| `min`/`max`| `int`, `float`    | inclusive numeric bounds                          |
| `allowed`  | all               | value must be one of the listed strings          |
| `allow_censored` | `int`, `float` | accept detection-limit values (`<0.01`, `ND`, …) |

Columns present in the file but absent from the schema are flagged as `unexpected_column` errors unless you pass `--no-strict`.

## Use as a library

```python
from lims_dq import load_schema, validate_dataframe, ErrorReport

ruleset = load_schema("schema.json")
import pandas as pd
df = pd.read_csv("samples.csv", dtype=str)
errors = validate_dataframe(df, ruleset)
report = ErrorReport("samples.csv", ruleset.name, ruleset.version, len(df), errors)
print(report.to_text())   # or report.to_json()
```

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e . && pip install pytest
pytest
```

## License

MIT — see [LICENSE](LICENSE).
