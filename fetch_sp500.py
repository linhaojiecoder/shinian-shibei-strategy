import subprocess, json, time

def fetch(code, start, end):
    r = subprocess.run(["westock", "kline", code, "--period", "day",
                        "--start", start, "--end", end], capture_output=True, text=True)
    return r.stdout

def parse(lines):
    rows = []
    for ln in lines.splitlines():
        ln = ln.strip()
        if not ln.startswith("|"): continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < 3: continue
        if cells[0] == "date" or "---" in cells[0]: continue
        try:
            rows.append((cells[0], float(cells[2])))
        except (ValueError, IndexError):
            continue
    return rows

all_rows = {}
for y in range(2021, 2027):
    start = f"{y}-01-01"
    end = f"{y}-12-31" if y < 2026 else "2026-10-19"
    out = fetch("sh513500", start, end)
    for d, v in parse(out):
        all_rows[d] = v
    time.sleep(3)
sorted_rows = sorted(all_rows.items())
print(f"标普500 ETF(513500): {len(sorted_rows)} 天, {sorted_rows[0][0]} ~ {sorted_rows[-1][0]}")

with open("backtest_data/prices.json") as f:
    data = json.load(f)
data["513500"] = sorted_rows
with open("backtest_data/prices.json", "w") as f:
    json.dump(data, f, ensure_ascii=False)
print("已合并，当前标的:", list(data.keys()))
