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

## Schema reference

| Key        | Applies to        | Meaning                                          |
|------------|-------------------|--------------------------------------------------|
| `dtype`    | all               | `string`, `int`, `float`, or `date`              |
| `required` | all               | missing values fail (missing column fails too)   |
| `pattern`  | all               | regex the full value must match                  |
| `min`/`max`| `int`, `float`    | inclusive numeric bounds                          |
| `allowed`  | all               | value must be one of the listed strings          |

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
