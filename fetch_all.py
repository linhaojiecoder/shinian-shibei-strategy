import subprocess, json, time

ETFS = {
    "510300": "sh510300",
    "159915": "sz159915",
    "513100": "sh513100",
    "518880": "sh518880",
}

def fetch(code, start, end):
    r = subprocess.run(["westock", "kline", code, "--period", "day",
                        "--start", start, "--end", end],
                       capture_output=True, text=True)
    return r.stdout

def parse(lines):
    rows = []
    for ln in lines.splitlines():
        ln = ln.strip()
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < 3:
            continue
        if cells[0] == "date" or "---" in cells[0]:
            continue
        try:
            date = cells[0]
            last = float(cells[2])
            rows.append((date, last))
        except (ValueError, IndexError):
            continue
    return rows

all_data = {}
for name, code in ETFS.items():
    all_rows = {}
    for y in range(2021, 2027):
        start = f"{y}-01-01"
        end = f"{y}-12-31" if y < 2026 else "2026-10-19"
        out = fetch(code, start, end)
        rows = parse(out)
        for d, v in rows:
            all_rows[d] = v
        time.sleep(3)  # 避免频率限制
    sorted_rows = sorted(all_rows.items())
    all_data[name] = sorted_rows
    print(f"{name}: {len(sorted_rows)} 天, {sorted_rows[0][0]} ~ {sorted_rows[-1][0]}", flush=True)

with open("backtest_data/prices.json", "w") as f:
    json.dump(all_data, f, ensure_ascii=False)
print("DONE")
