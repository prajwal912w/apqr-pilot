import math
from datetime import datetime
from statistics import mean, stdev



def check_spec(result, lsl, usl):
    if lsl is not None and result < lsl:
        return "OOS"
    if usl is not None and result > usl:
        return "OOS"
    return "PASS"


def compute_stats(values, lsl, usl):
    values = [float(v) for v in values]
    avg = mean(values)
    sigma = stdev(values) if len(values) >= 2 else 0.0
    cpk = None
    if sigma > 0:
        sides = []
        if usl is not None:
            sides.append((float(usl) - avg) / (3 * sigma))
        if lsl is not None:
            sides.append((avg - float(lsl)) / (3 * sigma))
        if sides:
            cpk = round(min(sides), 2)
    return {
        "count": len(values),
        "mean": round(avg, 2),
        "std": round(sigma, 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "cpk": cpk,
    }


def spec_limits(limits):
    """Pick one specification for a parameter's review period: the first
    available LSL/USL. Returns (lsl, usl, changed) - changed=True means the
    specification was not constant over the period, so one Cpk for the whole
    period would not be comparable."""
    pairs = list(limits)
    distinct = {(str(l), str(u)) for l, u in pairs}
    lsl = next((l for l, u in pairs if l is not None), None)
    usl = next((u for l, u in pairs if u is not None), None)
    return lsl, usl, len(distinct) > 1


def parameter_stats(values, limits):
    """Statistics for one parameter across the review period. This is the
    single source of truth for Cpk - every surface (dashboard, /api/summary,
    both conclusions) reports these numbers. Cpk uses the first available
    limits and is reported as None when the specification changed mid-period,
    because a single value would not be comparable."""
    lsl, usl, changed = spec_limits(limits)
    stats = compute_stats(values, lsl, usl)
    if changed:
        stats["cpk"] = None
    stats["lsl"] = float(lsl) if lsl is not None else None
    stats["usl"] = float(usl) if usl is not None else None
    stats["spec_changed"] = changed
    return stats


def validate_row(row):
    """Validate one CSV row from DictReader (values may be None or missing).
    Returns (errors, cleaned). cleaned holds normalized values: text fields
    stripped, numeric fields parsed as floats, and the original text kept so
    Decimal storage stays exact."""
    def get(key):
        return (row.get(key) or "").strip()

    cleaned = {
        "product": get("product"),
        "batch_no": get("batch_no"),
        "parameter": get("parameter"),
        "unit": get("unit"),
        "mfg_date": get("mfg_date"),
        "result_text": get("result"),
        "lsl_text": get("lsl"),
        "usl_text": get("usl"),
    }
    errors = []
    if not cleaned["product"]:
        errors.append("product is empty")
    if not cleaned["batch_no"]:
        errors.append("batch_no is empty")
    if not cleaned["parameter"]:
        errors.append("parameter is empty")

    def parse_number(text, column):
        if text == "":
            return None
        try:
            value = float(text)
        except ValueError:
            errors.append(f"{column} '{text}' is not a number")
            return None
        if not math.isfinite(value):
            errors.append(f"{column} '{text}' is not a finite number")
            return None
        return value

    if not cleaned["result_text"]:
        errors.append("result is empty")
        cleaned["result"] = None
    else:
        cleaned["result"] = parse_number(cleaned["result_text"], "result")
    cleaned["lsl"] = parse_number(cleaned["lsl_text"], "lsl")
    cleaned["usl"] = parse_number(cleaned["usl_text"], "usl")
    if cleaned["lsl"] is None and cleaned["usl"] is None:
        errors.append("no specification limit (need lsl or usl)")
    if (cleaned["lsl"] is not None and cleaned["usl"] is not None
            and cleaned["lsl"] > cleaned["usl"]):
        errors.append(f"lsl {cleaned['lsl']} is greater than usl {cleaned['usl']}")
    try:
        cleaned["date"] = datetime.strptime(cleaned["mfg_date"], "%Y-%m-%d").date()
    except ValueError:
        errors.append(f"mfg_date '{cleaned['mfg_date']}' is not YYYY-MM-DD")
        cleaned["date"] = None
    return errors, cleaned
