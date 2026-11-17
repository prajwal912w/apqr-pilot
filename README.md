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
| `ADMIN_PASSWORD` | first-run admin password (default `apqr123`) |
| `GROQ_API_KEY` / `GROQ_MODEL` | optional - enables the AI conclusion |
| `SESSION_COOKIE_SECURE` | `True` behind https |

Tables are created on first run, and a default `admin` user is seeded.

## API

| Route | Purpose |
| --- | --- |
| `POST /upload` | csv upload + validation |
| `GET /dashboard` | trend dashboard |
| `GET /api/summary` | stats + OOS per product/parameter |
| `GET /api/trend` | trend points for one parameter |
| `GET /api/results` | all results with pass/oos status |
| `GET /audit` | audit log page |
| `GET /audit/verify` | re-verify the hash chain |
| `GET /users` | admin user management |

## Project layout

```
app.py          routes, auth, audit chain, llm conclusion
models.py       sqlalchemy models (Product, Upload, Batch, Result, User, AuditLog)
analysis.py     spec checks + statistics
templates/      login, upload, dashboard, audit, users
good.csv        sample valid data (30 batches, 4 parameters)
bad.csv         sample invalid data
```
