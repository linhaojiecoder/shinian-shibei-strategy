#!/usr/bin/env python3
"""用腾讯原始接口（非 westock）拉取 5 只 ETF 真正的不复权历史价
腾讯 kline/kline 接口：param=<code>,day,<start>,<end>,<count>,<fq>
- fq 空 = 不复权（保留拆分跳空，这是正确的不复权价）
- 分段按年拉，绕过日期范围上限
输出 backtest_data/prices_true_nofq.json，格式 {code: [[date, [open, close]], ...]}
"""
import json, os, subprocess, time, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "backtest_data", "prices_true_nofq.json")

ETFS = [("510300", "sh510300"), ("159915", "sz159915"), ("513100", "sh513100"),
        ("513500", "sh513500"), ("518880", "sh518880")]
YEARS = list(range(2014, 2027))

def fetch(code, start, end):
    url = f"https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={code},day,{start},{end},800,"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def parse(d, code):
    data = d.get("data", {})
    if isinstance(data, dict) and code in data:
        day = data[code].get("day", [])
        # day: [date, open, close, high, low, volume]
        return [[x[0], [float(x[1]), float(x[2])]] for x in day if float(x[2]) > 0]
    return []

def main():
    result = {}
    for code, qt in ETFS:
        print(f"=== {code} ===", flush=True)
        all_rows = {}
        for year in YEARS:
            start = f"{year}-01-01"
            end = f"{year}-12-31"
            for attempt in range(4):
                try:
                    d = fetch(qt, start, end)
                    rows = parse(d, qt)
                    if rows:
                        for date, oc in rows:
                            all_rows[date] = oc
                        break
                    time.sleep(4)
                except Exception as e:
                    time.sleep(5)
            time.sleep(0.5)
        ordered = [[dd, oc] for dd, oc in sorted(all_rows.items())]
        result[code] = ordered
        print(f"  {code}: {len(ordered)} 天, {ordered[0][0]} ~ {ordered[-1][0]}", flush=True)

    json.dump(result, open(OUT, "w"), ensure_ascii=False)
    print(f"\n✅ 已写入 {OUT}")
    for code in result:
        arr = result[code]
        print(f"  {code}: {len(arr)} 天, {arr[0][0]} ~ {arr[-1][0]}")

if __name__ == "__main__":
    main()
