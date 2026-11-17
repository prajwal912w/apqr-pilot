import csv, random
from datetime import date, timedelta

random.seed(42)

rows = []
start = date(2026, 1, 5)
for i in range(30):
    batch = f"PCT{2601 + i}"
    d = (start + timedelta(days=12 * i)).isoformat()
    p = "Paracetamol Tablets 500 mg"

    assay = round(96.8 + i * 0.25 + random.uniform(-0.2, 0.2), 2)
    rows.append([p, batch, d, "Assay", "%", assay, 95.0, 105.0])

    diss = round(random.uniform(86, 96), 1)
    rows.append([p, batch, d, "Dissolution (30 min)", "%", diss, 80, ""])

    imp = round(random.uniform(0.15, 0.55), 2)
    rows.append([p, batch, d, "Total Impurities", "%", imp, "", 1.0])

    water = round(random.uniform(1.8, 3.2), 1)
    rows.append([p, batch, d, "Water Content (KF)", "%", water, "", 5.0])

# 3 deliberate OOS
rows[10][5] = 106.3   # assay above USL
rows[21][5] = 74.8    # dissolution below LSL
rows[34][5] = 1.12    # impurities above USL


with open("good.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["product","batch_no","mfg_date","parameter","unit","result","lsl","usl"])
    w.writerows(rows)


bad = [
    ["Paracetamol Tablets 500 mg","PCT9901","2026-05-01","Assay","%","",95.0,105.0],          # missing result
    ["Paracetamol Tablets 500 mg","PCT9902","32-13-2026","Assay","%",99.1,95.0,105.0],        # garbage date
    ["Paracetamol Tablets 500 mg","PCT9903","2026-05-01","Assay","%","high",95.0,105.0],      # text in result
]

with open("bad.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["product","batch_no","mfg_date","parameter","unit","result","lsl","usl"])
    w.writerows(bad)


print("good.csv:", len(rows), "rows + bad.csv: 3 bad rows")