#!/usr/bin/env python3
"""分段拉取 5 只 ETF 完整不复权历史价（bfq）
- 按年度分段请求，绕过 westock 单次 2000 条上限
- 输出 backtest_data/prices_rebuild_nofq.json
- 带节流 + 重试
"""
import json, os, subprocess, sys, time

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "backtest_data", "prices_rebuild_nofq.json")

ETFS = [
    ("510300", "sh510300"),
    ("159915", "sz159915"),
    ("513100", "sh513100"),
    ("513500", "sh513500"),
    ("518880", "sh518880"),
]
YEARS = list(range(2014, 2027))  # 2014 ~ 2026

def run_westock(code, start, end):
    cmd = ["westock", "kline", code, "--start", start, "--end", end]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return r.stdout

def parse_kline(text):
    rows = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line or "date" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        date = cells[0]
        try:
            openp = float(cells[1])
            close = float(cells[2])
        except ValueError:
            continue
        if date and openp > 0 and close > 0:
            rows[date] = [openp, close]
    return rows

def fetch_year(code, year, max_retry=4):
    start = f"{year}-01-01"
    end = f"{year}-12-31"
    for attempt in range(max_retry):
        text = run_westock(code, start, end)
        rows = parse_kline(text)
        if rows:
            return rows
        if "频繁" in text or "过于频繁" in text:
            wait = 12 * (attempt + 1)
            time.sleep(wait)
        else:
            time.sleep(6)
    return {}

def main():
    result = {}
    for code, qt in ETFS:
        print(f"=== {code} ===", flush=True)
        all_rows = {}
        for year in YEARS:
            rows = fetch_year(qt, year)
            if rows:
                all_rows.update(rows)
                print(f"  {year}: {len(rows)} 条", flush=True)
            else:
                print(f"  {year}: 空（可能停牌或数据缺失）", flush=True)
            time.sleep(3)
        ordered = [[d, oc] for d, oc in sorted(all_rows.items())]
        result[code] = ordered
        if ordered:
            print(f"  ✅ {code}: 共 {len(ordered)} 天, {ordered[0][0]} ~ {ordered[-1][0]}", flush=True)
        else:
            print(f"  ❌ {code}: 无数据", flush=True)

    json.dump(result, open(OUT, "w"), ensure_ascii=False)
    print(f"\n✅ 已写入 {OUT}")
    for code in result:
        arr = result[code]
        if arr:
            print(f"  {code}: {len(arr)} 天, {arr[0][0]} ~ {arr[-1][0]}")

if __name__ == "__main__":
    main()
