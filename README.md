# APQR Pilot

A small web app for Annual Product Quality Review (APQR) trend analysis. Upload batch results as CSV, and it validates every row, checks results against specification limits, computes process statistics (including Cpk), plots trends, flags out-of-specification (OOS) batches and adverse trends, keeps a tamper-evident audit trail, and drafts an AI-assisted review conclusion.

**Live demo:** https://apqr-pilot.onrender.com (`admin` / `apqr123`)

New here? See `GUIDE.md` for a 5-minute walkthrough.

## Features

- **CSV upload with row validation** - every row is checked (batch number, parameter, numeric result, numeric LSL/USL, valid mfg date). A file with any bad row is rejected with per-line errors; nothing partial is saved. Re-uploading the identical file is rejected by SHA-256 hash, and duplicate batches are rejected by a database constraint.
- **Specification checks** - each result is Pass/OOS against its limits. One-sided limits (only LSL or only USL) are handled.
- **Statistics** - count, mean, min, max, standard deviation and Cpk per product/parameter.
- **Trend dashboard** - per-parameter trend charts with spec bands, OOS points flagged, and spec-change detection (flags when limits changed mid-period).
- **Adverse trend flags** - sustained drift toward a limit is flagged even while results stay in spec.
- **Audit trail** - every login (success and failure), upload, rejection, user change and reset is appended to a hash-chained log (each entry links to the previous entry's SHA-256). A verify endpoint re-computes the chain and reports the first altered row, if any.
- **PDF report** - print-ready APQR summary (report id from the upload hash, period, stats, OOS list, conclusion).
- **AI-assisted conclusion** - the batch summary is sent to an LLM (Groq, `openai/gpt-oss-120b`) which drafts a short reviewer-style conclusion. Degrades gracefully: with no API key the section stays hidden.
- **User management** - admin-only page to create accounts and reset passwords; all actions audit-logged. Passwords stored as Werkzeug hashes, sessions are 30-minute, HttpOnly, SameSite cookies (Secure in production).

## Stack

Flask + PostgreSQL (SQLAlchemy, psycopg 3), vanilla JS charts on the dashboard, Groq API for the AI conclusion. Deployed on Render with a Neon Postgres database.

## CSV format

One row per result:

```
product,batch_no,parameter,unit,result,lsl,usl,mfg_date
Paracetamol Tablets 500 mg,PCT2601,Assay,%,99.8,95.0,105.0,2026-01-05
```

- `lsl`/`usl` may be blank for one-sided limits
- `mfg_date` must be `YYYY-MM-DD`
- any invalid row rejects the whole file with line-numbered errors

`good.csv` = 30 batches x 4 parameters with 2-3 intentional OOS results. `bad.csv` = malformed rows on purpose.

## Running locally

```bash
python -m venv .venv
.venv\Scripts\activate          # windows
pip install -r requirements.txt
flask --app app run
```

Environment variables:

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | flask session signing |
| `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_NAME` | postgres connection |
| `DB_SSLMODE` | `require` for hosted postgres, omit locally |
| `ADMIN_PASSWORD` | first-run admin password (required - no default; the app refuses to boot without it) |
| `GROQ_API_KEY` / `GROQ_MODEL` | optional - enables the AI conclusion |
| `SESSION_COOKIE_SECURE` | defaults to `True`; set `False` for local http |

Tables are created on first run, and the `admin` user is seeded from `ADMIN_PASSWORD`.

## API

| Route | Purpose |
| --- | --- |
| `POST /upload` | csv upload + validation |
| `GET /dashboard` | trend dashboard (`?product=` picks the product when several are uploaded) |
| `GET /api/summary` | stats + OOS per product/parameter |
| `GET /api/trend` | trend points for one parameter |
| `GET /api/results` | all results with pass/oos status |
| `GET /audit` | audit log page |
| `GET /audit/verify` | re-verify the hash chain |
| `GET /users` | admin user management |


## Database tables

| Table | Columns (key ones) | Constraints |
| --- | --- | --- |
| `products` | id, name | name unique |
| `uploads` | id, filename, file_hash, uploaded_at | file_hash unique (duplicate-file rejection) |
| `batches` | id, batch_no, mfg_date, product_id, upload_id | (product_id, batch_no) unique |
| `results` | id, batch_id, parameter, unit, result, lsl, usl | batch_id -> batches |
| `user` | id, username, password_hash | username unique |
| `audit_log` | id, username, action, detail, at, prev_hash, entry_hash | append-only, hash-chained |

There are no edit or delete routes for uploaded data - the only way data changes is a new upload.

## Calculations

- **Pass/OOS**: a result is OOS when it is below LSL or above USL; values exactly on a limit pass. Each row is judged against its own limits, so one-sided specs (only LSL or only USL) work.
- **SD**: sample standard deviation (`statistics.stdev`).
- **Cpk**: `min((USL - mean) / 3s, (mean - LSL) / 3s)`; with one limit only the existing side is used. When n < 2 or SD = 0, Cpk is reported as `n/a` instead of a misleading number. All statistics are computed once in `analysis.py` (`parameter_stats`) and every surface - dashboard, `/api/summary`, both conclusions - reports those same numbers. Cpk uses the first available limits; if the specification changed during the period, Cpk is reported as `n/a` (not comparable) rather than silently using one batch's limits.
- **Audit chain**: `sha256(server_secret | prev_hash | timestamp | username | action | detail)` per entry; `/audit/verify` recomputes the whole chain. The server secret is part of every hash, so someone with only database access cannot alter a row and rebuild a valid chain (tamper-evident; a leaked secret or tail deletion still needs an external anchor).
- **AI conclusion**: the LLM receives only statistics computed by `analysis.py` (stats + OOS batch lists) and is instructed to phrase, never calculate. A rule-based conclusion computed in code always shows, so the app works with no API key.

## Validation rules

Uploads are all-or-nothing: any bad row rejects the whole file with line-numbered errors. Checked: required columns present, product/batch_no/parameter/unit non-empty (whitespace-only counts as empty), results are never negative and never implausible (more than 10x outside their own limit is treated as a data error, while a real OOS near the limit is accepted), result numeric and finite (no NaN/inf), limits numeric with at least one present and LSL <= USL, mfg_date is YYYY-MM-DD, no duplicate (batch, parameter) rows inside one file, one batch cannot appear with two different mfg_dates, rows with missing cells are handled (no crash), file is .csv, UTF-8, under 2 MB, not empty, not a duplicate of a previous upload (SHA-256), and batches must not already exist in the database (clean 409).

## Testing

```bash
python -m pytest tests/ -v
```

24 tests cover two-sided and one-sided specs, values exactly on a limit, hand-calculated Cpk, one result, identical results (SD = 0), CSV row validation (whitespace-only values, missing cells, NaN/inf, LSL > USL, bad dates, empty unit, negative and implausible results), and spec-change handling (Cpk reported as not comparable).

## Project layout

```
app.py          routes, auth, audit chain, llm conclusion
models.py       sqlalchemy models (Product, Upload, Batch, Result, User, AuditLog)
analysis.py     spec checks, statistics + csv row validation
templates/      login, upload, dashboard, audit, users
good.csv        sample valid data (30 batches, 4 parameters)
bad.csv         sample invalid data
```
