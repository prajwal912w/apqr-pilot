import os
import hashlib
import csv
from decimal import Decimal
from flask import Flask, jsonify , request, session, render_template, redirect
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, func, Column, Integer, Numeric, String, TEXT, ForeignKey, UniqueConstraint
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import timedelta
from models import db, Product, Upload, Batch, Result, User, AuditLog
from datetime import datetime
from analysis import check_spec, parameter_stats, validate_row
from functools import wraps


app = Flask(__name__, static_url_path='')

app.config['SECRET_KEY'] = os.environ['SECRET_KEY']
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get("SESSION_COOKIE_SECURE", "True") == "True"  # set False for local http
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # reject uploads over 2 MB
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)


app.config["SQLALCHEMY_DATABASE_URI"] = URL.create(
    "postgresql+psycopg",
    username=os.environ.get("DB_USER", "postgres"),
    password=os.environ["DB_PASSWORD"],
    host=os.environ.get("DB_HOST", "localhost"),
    port=int(os.environ.get("DB_PORT", "5432")),
    database=os.environ.get("DB_NAME", "apqr_pilot"),
    query={"sslmode": os.environ["DB_SSLMODE"]} if os.environ.get("DB_SSLMODE") else {},
)


db.init_app(app)

with app.app_context():
    db.create_all()
    if not User.query.filter_by(username="admin").first():
        admin_password = os.environ.get("ADMIN_PASSWORD")
        if not admin_password:
            raise RuntimeError("Set the ADMIN_PASSWORD environment variable - the app has no default admin password.")
        db.session.add(User(username="admin", password_hash=generate_password_hash(admin_password)))
        db.session.commit()



def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")
        return view(*args, **kwargs)
    return wrapped

def log_action(action, detail):
    username = session.get("username", "anonymous")
    at = datetime.utcnow()
    last = AuditLog.query.order_by(AuditLog.id.desc()).first()
    prev_hash = last.entry_hash if last else "GENESIS"
    # the server secret goes into every hash: someone with only database
    # access cannot recompute the chain after altering it
    payload = f"{app.config['SECRET_KEY']}|{prev_hash}|{at.isoformat()}|{username}|{action}|{detail}"
    entry_hash = hashlib.sha256(payload.encode()).hexdigest()
    db.session.add(AuditLog(username=username, action=action, detail=detail, at=at,
                            prev_hash=prev_hash, entry_hash=entry_hash))


@app.route("/upload", methods=["GET","POST"])
@login_required
def upload_page():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            return {"error": "No File selected"}, 400
        if not file.filename.lower().endswith(".csv"):
            return {"error": "Only CSV files are accepted"}, 400
        content = file.read()
        file_hash = hashlib.sha256(content).hexdigest()
        existing = Upload.query.filter_by(file_hash=file_hash).first()
        if existing:
            log_action("UPLOAD_REJECTED", f"duplicate file: {file.filename}")
            db.session.commit()
            return {"error": "This file was already uploaded"}, 409
        try:
            text = content.decode("utf-8-sig").splitlines()
        except UnicodeDecodeError:
            return {"error": "File is not valid UTF-8 text"}, 400
        reader = csv.DictReader(text)
        required = {"product", "batch_no", "parameter", "result", "lsl", "usl", "mfg_date"}
        missing_headers = required - set(reader.fieldnames or [])
        if missing_headers:
            return {"error": "Missing columns", "details": [f"missing column: {h}" for h in sorted(missing_headers)]}, 400
        errors = []
        data_rows = []
        seen_rows = {}
        batch_dates = {}
        for line_number, row in enumerate(reader, start=2):
            row_errors, cleaned = validate_row(row)
            bn, prm = cleaned["batch_no"], cleaned["parameter"]
            if bn and prm:
                key = (bn, prm)
                if key in seen_rows:
                    row_errors.append(f"duplicate row for batch {bn} / {prm} (first on line {seen_rows[key]})")
                else:
                    seen_rows[key] = line_number
            if bn and cleaned["date"] is not None:
                key = (cleaned["product"], bn)
                previous = batch_dates.get(key)
                if previous is None:
                    batch_dates[key] = cleaned["date"]
                elif previous != cleaned["date"]:
                    row_errors.append(f"batch {bn} has inconsistent mfg_date ({previous} on an earlier line, {cleaned['date']} here)")
            for msg in row_errors:
                errors.append(f"line {line_number}: {msg}")
            if not row_errors:
                data_rows.append(cleaned)
        if errors:
            log_action("UPLOAD_REJECTED", f"invalid csv {file.filename}: {len(errors)} errors")
            db.session.commit()
            return {"error": "Invalid CSV", "details": errors}, 400
        row_count = len(data_rows)
        if row_count == 0:
            return {"error": "CSV has no data rows"}, 400
        try:
            upload = Upload(filename=file.filename, file_hash=file_hash)
            db.session.add(upload)
            db.session.flush()
            product_cache = {}
            batch_cache = {}
            for row in data_rows:
                product_name = row["product"]
                product = product_cache.get(product_name)
                if product is None:
                    product = Product.query.filter_by(name=product_name).first()
                    if product is None:
                        product = Product(name=product_name)
                        db.session.add(product)
                        db.session.flush()
                    product_cache[product_name] = product
                key = (product.id, row["batch_no"])
                batch = batch_cache.get(key)
                if batch is None:
                    batch = Batch(
                        batch_no=row["batch_no"],
                        mfg_date=row["date"],
                        product_id=product.id,
                        upload_id=upload.id,
                    )
                    db.session.add(batch)
                    db.session.flush()
                    batch_cache[key] = batch
                db.session.add(Result(
                    batch_id=batch.id,
                    parameter=row["parameter"],
                    unit=row["unit"],
                    result=Decimal(row["result_text"]),
                    lsl=Decimal(row["lsl_text"]) if row["lsl_text"] else None,
                    usl=Decimal(row["usl_text"]) if row["usl_text"] else None,
                ))
            log_action("UPLOAD_ACCEPTED", f"{file.filename}: {row_count} rows, {len(batch_cache)} batches")
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return {"error": "These batches already exist in the database"}, 409
        return {"message": f"Saved {row_count} results across {len(batch_cache)} batches"}, 200
    return render_template("upload.html")


@app.route("/api/summary")
@login_required
def summary():
    output = []
    for product in Product.query.all():
        parameters = (db.session.query(Result.parameter)
                      .join(Batch, Result.batch_id == Batch.id)
                      .filter(Batch.product_id == product.id)
                      .distinct().all())
        for (parameter,) in parameters:
            rows = (db.session.query(Result, Batch)
                    .join(Batch, Result.batch_id == Batch.id)
                    .filter(Batch.product_id == product.id, Result.parameter == parameter)
                    .order_by(Batch.mfg_date).all())
            values = [float(r.result) for r, b in rows]
            stats = parameter_stats(values, [(r.lsl, r.usl) for r, b in rows])
            oos = [b.batch_no for r, b in rows if check_spec(r.result, r.lsl, r.usl) == "OOS"]
            output.append({
                "product": product.name,
                "parameter": parameter,
                "stats": stats,
                "oos_batches": oos,
                "status": "OOS" if oos else "PASS",
            })
    return {"summary": output}


@app.route("/api/trend")
@login_required
def trend():
    product_name = request.args.get("product")
    parameter = request.args.get("parameter")
    if not product_name or not parameter:
        return {"error": "product and parameter are required"}, 400
    product = Product.query.filter_by(name=product_name).first()
    if not product:
        return {"error": "product not found"}, 404
    rows = (db.session.query(Result, Batch)
            .join(Batch, Result.batch_id == Batch.id)
            .filter(Batch.product_id == product.id, Result.parameter == parameter)
            .order_by(Batch.mfg_date).all())
    if not rows:
        return {"error": "no data for that parameter"}, 404
    specs = {(str(r.lsl), str(r.usl)) for r, b in rows}
    points = []
    for r, b in rows:
        points.append({
            "batch_no": b.batch_no,
            "mfg_date": b.mfg_date.isoformat(),
            "result": float(r.result),
            "status": check_spec(r.result, r.lsl, r.usl),
            "lsl": float(r.lsl) if r.lsl is not None else None,
            "usl": float(r.usl) if r.usl is not None else None,
        })
    first = rows[0][0]
    return {
        "product": product.name,
        "parameter": parameter,
        "unit": first.unit,
        "lsl": float(first.lsl) if first.lsl is not None else None,
        "usl": float(first.usl) if first.usl is not None else None,
        "spec_changed": len(specs) > 1,
        "points": points,
    }


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session["user_id"] = user.id
            session["username"] = user.username
            session.permanent = True
            log_action("LOGIN_SUCCESS", f"{username} logged in")
            db.session.commit()
            return redirect("/dashboard")
        log_action("LOGIN_FAILED", f"failed login for username '{username}'")
        db.session.commit()
        error = "Invalid username or password"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/audit")
@login_required
def audit_page():
    entries = AuditLog.query.order_by(AuditLog.at.desc()).all()
    return render_template("audit.html", entries=entries)

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("username") != "admin":
            return redirect("/dashboard")
        return view(*args, **kwargs)
    return wrapped


@app.route("/users", methods=["GET", "POST"])
@login_required
@admin_required
def users_page():
    error = message = None
    if request.method == "POST":
        action = request.form.get("action")
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if action == "create":
            if not username or not password:
                error = "Username and password are required."
            elif User.query.filter_by(username=username).first():
                error = "That username is taken."
            else:
                db.session.add(User(username=username,
                                    password_hash=generate_password_hash(password)))
                log_action("USER_CREATED", f"admin created user '{username}'")
                db.session.commit()
                message = f"User '{username}' created."
        elif action == "reset":
            user = User.query.filter_by(username=username).first()
            if not user or not password:
                error = "User not found or password empty."
            else:
                user.password_hash = generate_password_hash(password)
                log_action("PASSWORD_RESET", f"admin reset password for '{username}'")
                db.session.commit()
                message = f"Password reset for '{username}'."
    users = User.query.order_by(User.username).all()
    return render_template("users.html", users=users, error=error, message=message)


@app.route("/")
def index():
    return redirect("/dashboard")


def rule_conclusion(payload):
    """Written conclusion computed entirely by our code - works with no LLM key."""
    if not payload["params"]:
        return None
    lines = []
    oos_parts = []
    for p in payload["params"]:
        stats = p["stats"]
        if p["oos_batches"]:
            oos_parts.append(f"{p['name']} ({', '.join(p['oos_batches'])})")
        cpk = stats["cpk"]
        if cpk is None:
            reason = "specification changed during the period" if stats.get("spec_changed") else "too little data or zero variation"
            lines.append(f"{p['name']}: Cpk n/a ({reason}).")
        elif cpk < 1.0:
            lines.append(f"{p['name']}: Cpk {cpk} - process is not consistently capable of meeting spec.")
        elif cpk < 1.33:
            lines.append(f"{p['name']}: Cpk {cpk} - marginally capable, watch this parameter.")
        else:
            lines.append(f"{p['name']}: Cpk {cpk} - capable of meeting spec.")
    if oos_parts:
        lines.insert(0, "Out-of-specification results in " + "; ".join(oos_parts) + ".")
    else:
        lines.insert(0, "All results within specification limits.")
    return "\n".join("- " + line for line in lines)

def apqr_payload(product_name=None):
    # everything the dashboard page needs, in the shape its script expects:
    # {product, report_id, file_hash, params:[{name, unit, rows:[...]}]}
    if product_name:
        product = Product.query.filter_by(name=product_name).first()
    else:
        product = Product.query.order_by(Product.id).first()
    latest = Upload.query.order_by(Upload.id.desc()).first()
    params = []
    if product:
        parameters = (db.session.query(Result.parameter)
                      .join(Batch, Result.batch_id == Batch.id)
                      .filter(Batch.product_id == product.id)
                      .distinct().all())
        for (parameter,) in parameters:
            rows = (db.session.query(Result, Batch)
                    .join(Batch, Result.batch_id == Batch.id)
                    .filter(Batch.product_id == product.id, Result.parameter == parameter)
                    .order_by(Batch.mfg_date).all())
            params.append({
                "name": parameter,
                "unit": rows[0][0].unit if rows else "",
                "stats": parameter_stats([float(r.result) for r, b in rows],
                                         [(r.lsl, r.usl) for r, b in rows]),
                "oos_batches": [b.batch_no for r, b in rows
                                if check_spec(r.result, r.lsl, r.usl) == "OOS"],
                "rows": [{
                    "batch": b.batch_no,
                    "date": b.mfg_date.isoformat(),
                    "result": float(r.result),
                    "lsl": float(r.lsl) if r.lsl is not None else None,
                    "usl": float(r.usl) if r.usl is not None else None,
                } for r, b in rows],
            })
    file_hash = latest.file_hash if latest else "DRAFT"
    payload = {
        "product": product.name if product else "No data yet",
        "products": [p.name for p in Product.query.order_by(Product.id).all()],
        "report_id": f"APQR-{datetime.now().year}-{file_hash[:8].upper()}",
        "file_hash": file_hash[:12],
        "params": params,
    }
    payload["conclusion"] = rule_conclusion(payload)
    payload["ai_conclusion"] = llm_conclusion(payload)
    return payload

def llm_conclusion(payload):
    import json, urllib.request
    key = os.environ.get("GROQ_API_KEY")
    if not key or not payload["params"]:
        return None
    # every number below is computed by OUR code (compute_stats/check_spec) -
    # the model only phrases them, it never calculates or invents values
    parameters = [{
        "name": p["name"], "unit": p["unit"],
        "lsl": p["stats"]["lsl"], "usl": p["stats"]["usl"],
        "stats": p["stats"], "oos_batches": p["oos_batches"],
    } for p in payload["params"]]
    summary = {
        "product": payload["product"],
        "batches": len(payload["params"][0]["rows"]),
        "parameters": parameters,
    }
    prompt = ("You are a pharmaceutical quality reviewer writing the overall conclusion of an Annual Product Quality Review. "
              "Use only the calculated statistics below - they were computed by the application code, so never recalculate or invent numbers. "
              "Write 3-4 short bullet points, one per line, each starting with '- ': whether the process is in a state of control, "
              "any out-of-specification batches named in oos_batches, any parameter with Cpk below 1.0, "
              "and any trend worth watching. Name batches exactly as they appear in oos_batches. "
              "Plain text only, no markdown, no asterisks. Quote values exactly as given. No filler.\n\n" + json.dumps(summary))
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}]}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}", "User-Agent": "curl/8.1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            out = json.loads(resp.read())
        return out["choices"][0]["message"]["content"].strip().replace("**", "")
    except Exception as e:
        print("llm_conclusion failed:", e)
        return None

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", data=apqr_payload(request.args.get("product")))

@app.route("/api/results")
@login_required
def results():
     rows = (db.session.query(Result, Batch, Product)
            .join(Batch, Result.batch_id == Batch.id)
            .join(Product, Batch.product_id == Product.id)
            .order_by(Batch.mfg_date).all())
     return {"results": [{
            "product": p.name,
            "batch_no": b.batch_no,
            "mfg_date": b.mfg_date.isoformat(),
            "parameter": r.parameter,
            "unit": r.unit,
            "result": float(r.result),
            "lsl": float(r.lsl) if r.lsl is not None else None,
            "usl": float(r.usl) if r.usl is not None else None,
            "status": check_spec(r.result, r.lsl, r.usl),
        } for r, b, p in rows]}

@app.route("/audit/verify")
@login_required
def audit_verify():
    entries = AuditLog.query.order_by(AuditLog.id).all()
    prev = "GENESIS"
    for e in entries:
        payload = f"{app.config['SECRET_KEY']}|{prev}|{e.at.isoformat()}|{e.username}|{e.action}|{e.detail}"
        expected = hashlib.sha256(payload.encode()).hexdigest()
        if e.prev_hash != prev or e.entry_hash != expected:
            return (f'<div class="verify-banner fail">Chain broken at entry #{e.id} '
                    f'({e.action}, {e.at:%Y-%m-%d %H:%M} UTC). This row or an earlier one was altered.</div>')
        prev = e.entry_hash
    return f'<div class="verify-banner ok">Chain intact - {len(entries)} entries verified.</div>'

@app.context_processor
def report_footer():
    latest = Upload.query.order_by(Upload.id.desc()).first()
    period = db.session.query(func.min(Batch.mfg_date), func.max(Batch.mfg_date)).first()
    return {"latest_upload": latest, "period": period, "now": datetime.now()}
