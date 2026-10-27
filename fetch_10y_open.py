#!/usr/bin/env python3
"""拉取 5 只 ETF 从 2016-01-01 到现在的日线（含开盘价+收盘价）
用于十年回测（无前视偏差：次日开盘成交）。
"""
import subprocess, json, time, sys

ETFS = {
    "510300": "sh510300",
    "159915": "sz159915",
    "513100": "sh513100",
    "513500": "sh513500",
    "518880": "sh518880",
}

START_YEAR = 2016
END_DATE = "2026-10-23"  # 最新交易日

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
            openp = float(cells[1])
            last = float(cells[2])
            rows.append((date, [openp, last]))
        except (ValueError, IndexError):
            continue
    return rows

all_data = {}
for name, code in ETFS.items():
    all_rows = {}
    for y in range(START_YEAR, 2027):
        start = f"{y}-01-01"
        end = END_DATE if y == 2026 else f"{y}-12-31"
        out = fetch(code, start, end)
        rows = parse(out)
        for d, v in rows:
            all_rows[d] = v
        print(f"  {name} {y}: +{len(rows)} 天", flush=True)
        time.sleep(1.5)
    sorted_rows = sorted(all_rows.items())
    all_data[name] = sorted_rows
    print(f"{name}: 共 {len(sorted_rows)} 天, {sorted_rows[0][0]} ~ {sorted_rows[-1][0]}", flush=True)

with open("backtest_data/prices_10y_open.json", "w") as f:
    json.dump(all_data, f, ensure_ascii=False)
print("\n✅ 已保存 backtest_data/prices_10y_open.json")
for k, v in all_data.items():
    print(f"  {k}: {len(v)} 天, {v[0][0]} ~ {v[-1][0]}")
