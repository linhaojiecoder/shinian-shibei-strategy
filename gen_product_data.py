#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 product_site/index.html 的 window.DATA（v3 策略 2014-2026 全周期报告）

用 sim_full_v3.json（v3 策略净值/持仓）+ prices_full_open.json（算基准曲线）。
输出：window.DATA 字段对齐旧报告页（dates/nav/base/hs300/yearly/weights/summary/start/end）。
"""
import json, os, statistics

BASE = os.path.dirname(os.path.abspath(__file__))
SIM = json.load(open(os.path.join(BASE, "backtest_data", "sim_full_v3.json")))
PRICE = json.load(open(os.path.join(BASE, "backtest_data", "prices_full_open.json")))

NAMES = ["510300", "159915", "513100", "513500", "518880"]
LABEL = {"510300": "沪深300", "159915": "创业板", "513100": "纳指",
         "513500": "标普500", "518880": "黄金"}

# ---- 1. 策略净值 ----
nav_series = SIM["nav_series"]
dates = [x["date"] for x in nav_series]
nav = [x["nav"] for x in nav_series]

# ---- 2. 五资产等权基准 + 沪深300 基准 ----
# 用收盘价算每只的净值（起点 2014-01 归一），再等权合成
close = {n: {d: v[1] for d, v in PRICE[n]} for n in NAMES}
# 对齐到策略的日期序列
date_map = {d: i for i, d in enumerate(dates)}
start_d = dates[0]
# 每只标的的净值序列
asset_nav = {}
for n in NAMES:
    c0 = close[n][start_d]
    asset_nav[n] = [close[n][d] / c0 for d in dates]

base = []   # 五资产等权
hs300 = asset_nav["510300"]
for i in range(len(dates)):
    base.append(sum(asset_nav[n][i] for n in NAMES) / len(NAMES))

# ---- 3. 逐年收益 + 最大回撤 ----
yearly = []
nav_by_year = {}
for i, d in enumerate(dates):
    y = d[:4]
    nav_by_year.setdefault(y, []).append((d, nav[i]))

year_ret = SIM["summary"]["year_ret"]  # 已算好的年度收益

for y in sorted(nav_by_year):
    seg = nav_by_year[y]
    # 年末净值
    end_nav = seg[-1][1]
    # 该年最大回撤（年内）
    peak = 0
    mdd = 0
    for _, v in seg:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0
        mdd = max(mdd, dd)
    ret = year_ret.get(y, 0)
    yearly.append({"year": int(y), "ret": ret, "mdd": round(mdd * 100, 2),
                   "end_nav": round(end_nav, 4)})

# ---- 4. 持仓权重（对齐旧报告 weights: [[date, {label: weight}], ...]）----
hold_series = SIM["hold_series"]
# hold_series 里 holds 是 {label: 市值}
weights = []
for i, h in enumerate(hold_series):
    holds = h["holds"]  # {label: 市值}
    total_mv = sum(holds.values())
    w = {}
    for n in NAMES:
        lb = LABEL[n]
        mv = holds.get(lb, 0)
        w[lb] = round(mv / total_mv, 4) if total_mv > 0 else 0.0
    weights.append([dates[i], w])

# ---- 5. summary ----
s = SIM["summary"]
summary = {
    "ann": s["ann"],
    "total_ret": s["total_ret"],
    "mdd": s["mdd"],
    "sharpe": s["sharpe"],
    "calmar": s["calmar"],
    "trades": s["trades"],
    "final_total": s["final_total"],
    "final_nav": nav[-1],
}

DATA = {
    "dates": dates,
    "nav": [round(v, 6) for v in nav],
    "base": [round(v, 6) for v in base],
    "hs300": [round(v, 6) for v in hs300],
    "yearly": yearly,
    "weights": weights,
    "summary": summary,
    "start": "2014-01",
    "end": "2026-10",
    "years": round(len(nav) / 244, 1),
}

out = os.path.join(BASE, "product_site", "data_v3.json")
json.dump(DATA, open(out, "w"), ensure_ascii=False)
print("已生成", out)
print("区间:", DATA["start"], "~", DATA["end"], "共", len(dates), "天")
print("summary:", json.dumps(summary, ensure_ascii=False))
print("yearly 条数:", len(yearly), "首:", yearly[0], "末:", yearly[-1])
print("weights 条数:", len(weights))
print("策略末净值:", round(nav[-1], 4), "五资产等权末净值:", round(base[-1], 4), "沪深300末净值:", round(hs300[-1], 4))
