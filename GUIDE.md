# APQR Pilot - Reviewer Guide

Everything below works in the browser, nothing to install. Takes about 5 minutes.

**App:** https://apqr-pilot.onrender.com
**Sign in:** username `admin`, password `apqr123`

## 1. Upload the sample data

1. Sign in, then go to **Upload**.
2. Choose `good.csv` from the repo and submit.
3. You'll get a confirmation: 120 results across 30 batches.

This file covers 30 batches of a dummy product (Paracetamol Tablets 500 mg) across 4 parameters - Assay, Dissolution, Total Impurities, Water Content. A few batches are intentionally out of spec so the flags are visible.

## 2. Open the dashboard

- One trend chart per parameter, with the spec limits drawn as bands.
- Out-of-spec batches are flagged in red (look for PCT2603, PCT2606, PCT2609).
- Below the charts: the stats table (count, mean, min/max, std dev, Cpk) and Pass/OOS status per parameter.
- **Print / PDF** button produces the APQR summary report.
- At the bottom, the **AI-assisted review** - a short conclusion drafted by an LLM from the actual batch numbers.

## 3. See validation reject a bad file

1. Go back to **Upload** and submit `bad.csv`.
2. The whole file is rejected, with the exact line numbers and what is wrong on each.
3. Nothing from the file is saved - it's all or nothing.

Try uploading `good.csv` a second time too - it's rejected as a duplicate by its file hash.

## 4. Check the audit trail

- Open **Audit**: every login, upload and rejection is listed.
- Each entry is chained to the one before it with a SHA-256 hash - editing any past entry breaks the chain.
- Click **verify chain** to re-check the whole log. It should report the chain intact.

## 5. User management (admin only)

- Open **Users** to create a new account or reset a password.
- Every change here is also recorded in the audit log.

## Notes

- All data is dummy data generated for this pilot.
- The app is a Flask + PostgreSQL project, deployed on Render with a Neon database. Code, setup instructions and the API list are in `README.md`.
