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
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf
from datetime import timedelta
from models import db, Product, Upload, Batch, Result, User, AuditLog
from datetime import datetime
from analysis import check_spec, compute_stats
from functools import wraps


app = Flask(__name__, static_url_path='')

app.config['SECRET_KEY'] = os.environ['SECRET_KEY']
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get("SESSION_COOKIE_SECURE", "False") == "True"
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
        db.session.add(User(username="admin", password_hash=generate_password_hash(os.environ.get("ADMIN_PASSWORD", "apqr123"))))
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
    last = AuditLog.query.order_by(AuditLog.id.desc()).first()
    prev_hash = last.entry_hash if last else "GENESIS"
    payload = f"{prev_hash}|{username}|{action}|{detail}"
    entry_hash = hashlib.sha256(payload.encode()).hexdigest()
    db.session.add(AuditLog(username=username, action=action, detail=detail,
                            prev_hash=prev_hash, entry_hash=entry_hash))


@app.route("/upload", methods=["GET","POST"])
@login_required
def upload_page():
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            return {"error": "No File selected"}, 400
        content = file.read()
        file_hash = hashlib.sha256(content).hexdigest()
        existing = Upload.query.filter_by(file_hash=file_hash).first()
        if existing:
            log_action("UPLOAD_REJECTED", f"duplicate file: {file.filename}")
            db.session.commit()
            return {"error": "This file was already uploaded"}, 409
        text = content.decode("utf-8").splitlines()
        reader = csv.DictReader(text)
        errors = []
        data_rows = []
        for line_number, row in enumerate(reader, start=2):
            row_errors = []
            if not row.get("batch_no"):
                row_errors.append("batch_no is empty")
            if not row.get("parameter"):
                row_errors.append("parameter is empty")
            try:
                float(row["result"])
            except (ValueError, TypeError):
                row_errors.append(f"result '{row.get('result')}' is not a number")
            for col in ("lsl", "usl"):
                value = row.get(col)
                if value and value.strip():
                    try:
                        float(value)
                    except ValueError:
                        row_errors.append(f"{col} '{value}' is not a number")
            try:
                datetime.strptime(row["mfg_date"], "%Y-%m-%d")
            except (ValueError, TypeError):
                row_errors.append(f"mfg_date '{row.get('mfg_date')}' is not YYYY-MM-DD")
            for msg in row_errors:
                errors.append(f"line {line_number}: {msg}")
            if not row_errors:
                data_rows.append(row)
        if errors:
            log_action("UPLOAD_REJECTED", f"invalid csv {file.filename}: {len(errors)} errors")
            db.session.commit()
            return {"error": "Invalid CSV", "details": errors}, 400
        row_count = len(data_rows)
        print(f"filename: {file.filename}")
        print(f"hash: {file_hash}")
        print(f"rows: {row_count}")
        upload = Upload(filename=file.filename, file_hash=file_hash)
        db.session.add(upload)
        db.session.flush()
        product_cache = {}
        batch_cache = {}
        for row in data_rows:
            product_name = row["product"].strip()
            product = product_cache.get(product_name)
            if product is None:
                product = Product.query.filter_by(name=product_name).first()
                if product is None:
                    product = Product(name=product_name)
                    db.session.add(product)
                    db.session.flush()
                product_cache[product_name] = product
            key = (product.id, row["batch_no"].strip())
            batch = batch_cache.get(key)
            if batch is None:
                batch = Batch(
                    batch_no=row["batch_no"].strip(),
                    mfg_date=datetime.strptime(row["mfg_date"], "%Y-%m-%d").date(),
                    product_id=product.id,
                    upload_id=upload.id,
                )
                db.session.add(batch)
                db.session.flush()
                batch_cache[key] = batch
            db.session.add(Result(
                batch_id=batch.id,
                parameter=row["parameter"].strip(),
                unit=(row.get("unit") or "").strip(),
                result=Decimal(row["result"]),
                lsl=Decimal(row["lsl"]) if row["lsl"].strip() else None,
                usl=Decimal(row["usl"]) if row["usl"].strip() else None,
            ))
        try:
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
            values = [r.result for r, b in rows]
            lsl = next((r.lsl for r, b in rows if r.lsl is not None), None)
            usl = next((r.usl for r, b in rows if r.usl is not None), None)
            stats = compute_stats(values, lsl, usl)
            oos = [b.batch_no for r, b in rows if check_spec(r.result, lsl, usl) == "OOS"]
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

def apqr_payload():
    # everything the dashboard page needs, in the shape its script expects:
    # {product, report_id, file_hash, params:[{name, unit, rows:[...]}]}
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
        "report_id": f"APQR-{datetime.now().year}-{file_hash[:8].upper()}",
        "file_hash": file_hash[:12],
        "params": params,
    }
    payload["ai_conclusion"] = llm_conclusion(payload)
    return payload

def llm_conclusion(payload):
    import json, urllib.request
    key = os.environ.get("GROQ_API_KEY")
    if not key or not payload["params"]:
        return None
    summary = {
        "product": payload["product"],
        "batches": len(payload["params"][0]["rows"]),
        "parameters": [{
            "name": p["name"], "unit": p["unit"],
            "results": [r["result"] for r in p["rows"]],
            "lsl": p["rows"][0]["lsl"], "usl": p["rows"][0]["usl"],
        } for p in payload["params"]],
    }
    prompt = ("You are a pharmaceutical quality reviewer writing the overall conclusion of an Annual Product Quality Review. "
              "Given the batch results below as JSON, write 3-4 short bullet points, one per line, each starting with '- ': "
              "whether the process is in a state of control, any out-of-specification results with batch numbers, "
              "and any trend worth watching. Quote result values exactly as they appear in the data. No filler.\n\n" + json.dumps(summary))
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}]}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}", "User-Agent": "curl/8.1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            out = json.loads(resp.read())
        return out["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print("llm_conclusion failed:", e)
        return None

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", data=apqr_payload())

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
        payload = f"{prev}|{e.username}|{e.action}|{e.detail}"
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
