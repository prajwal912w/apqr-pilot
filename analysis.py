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