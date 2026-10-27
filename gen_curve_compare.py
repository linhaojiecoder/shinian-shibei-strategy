#!/usr/bin/env python3
"""生成多策略净值曲线对比数据（含最大回撤），供前端可视化"""
import json, os
from datetime import datetime
import statistics

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "backtest_data", "prices_10y_open.json")

NAMES = ["510300","159915","513100","513500","518880"]
LABEL = {"510300":"沪深300","159915":"创业板","513100":"纳指","513500":"标普500","518880":"黄金"}

CAPITAL = 3_000_000
COST = 0.0008
START = "2016-01-01"

data = json.load(open(DATA))
date_sets = [set(d for d,_ in data[n]) for n in NAMES]
DATES = sorted(set.intersection(*date_sets))
DATES = [d for d in DATES if d >= START]
CLOSE = {n:{d:v[1] for d,v in data[n]} for n in NAMES}
OPENP = {n:{d:v[0] for d,v in data[n]} for n in NAMES}

def is_friday(d):
    return datetime.strptime(d, "%Y-%m-%d").weekday() == 4

def rebalance_day(i, freq):
    d = DATES[i]
    if freq == 'weekly':
        return is_friday(d)
    elif freq == 'biweekly':
        return is_friday(d) and (i // 5) % 2 == 0
    elif freq == 'monthly':
        return d[5:7] != DATES[i-1][5:7] if i > 0 else False
    return False

def compute_mdd(navs):
    """返回 (最大回撤百分比, 回撤起点idx, 回撤谷底idx)"""
    peak = navs[0]; mdd = 0; peak_idx = 0; trough_idx = 0
    cur_peak_idx = 0
    for i, v in enumerate(navs):
        if v > peak:
            peak = v; cur_peak_idx = i
        dd = (peak - v) / peak
        if dd > mdd:
            mdd = dd; peak_idx = cur_peak_idx; trough_idx = i
    return mdd*100, peak_idx, trough_idx

def stats(navs):
    years = len(navs)/244
    ann = ((navs[-1]/navs[0])**(1/years)-1)*100
    peak = navs[0]; mdd = 0
    for v in navs:
        peak = max(peak, v); mdd = max(mdd, (peak-v)/peak)
    rets = [navs[i]/navs[i-1]-1 for i in range(1,len(navs))]
    sharpe = statistics.mean(rets)/statistics.pstdev(rets)*(244**0.5) if statistics.pstdev(rets)>0 else 0
    return ann, mdd*100, sharpe

def backtest_nav(ma_n, freq, md, top_k, vol_on):
    holdings = {}
    cash = CAPITAL
    nav_series = []
    pending_target = None
    pending_stop = set()

    for i, d in enumerate(DATES):
        if i > 0 and (pending_target is not None or pending_stop):
            for code in list(pending_stop):
                if code in holdings:
                    h = holdings.pop(code)
                    p = OPENP[code][d]
                    cash += h["shares"] * p * (1 - COST)
            if pending_target is not None:
                for code in list(holdings.keys()):
                    if code not in pending_target and code not in pending_stop:
                        h = holdings.pop(code)
                        p = OPENP[code][d]
                        cash += h["shares"]*p*(1-COST)
                if pending_target:
                    mv = sum(holdings[c]["shares"]*OPENP[c][d] for c in holdings)
                    total = cash + mv
                    each = total / len(pending_target)
                    for code in pending_target:
                        p = OPENP[code][d]
                        cur_sh = holdings.get(code, {}).get("shares", 0)
                        diff = each - cur_sh * p
                        if diff > p:
                            sh = int(diff / (p*(1+COST))) // 100 * 100
                            if sh > 0:
                                holdings[code] = {"shares": holdings.get(code,{}).get("shares",0) + sh}
                                cash -= sh*p*(1+COST)
            pending_target = None
            pending_stop = set()

        if ma_n > 0 and i >= ma_n:
            for code in list(holdings.keys()):
                ma = sum(CLOSE[code][DATES[j]] for j in range(i-ma_n+1, i+1)) / ma_n
                if CLOSE[code][d] < ma:
                    pending_stop.add(code)

        if rebalance_day(i, freq) and i >= md:
            metrics = {}
            for n in NAMES:
                mom = CLOSE[n][d] / CLOSE[n][DATES[i-md]] - 1
                ma = sum(CLOSE[n][DATES[j]] for j in range(i-ma_n+1,i+1)) / ma_n if ma_n>0 else 0
                rets = [CLOSE[n][DATES[j]]/CLOSE[n][DATES[j-1]]-1 for j in range(i-20+1,i+1)]
                m = sum(rets)/len(rets)
                vol = (sum((r-m)**2 for r in rets)/len(rets))**0.5
                above = CLOSE[n][d] > ma if ma_n>0 else True
                metrics[n] = {"mom":mom, "above":above, "vol":vol}
            ranked = sorted(NAMES, key=lambda n: metrics[n]["mom"], reverse=True)
            target = []
            for n in ranked[:top_k]:
                if metrics[n]["mom"]>0 and metrics[n]["above"]:
                    if vol_on and metrics[n]["vol"] > 0.02:
                        continue
                    target.append(n)
            pending_target = target

        mv = sum(holdings[c]["shares"]*CLOSE[c][d] for c in holdings)
        nav_series.append((cash + mv) / CAPITAL)

    return nav_series

def buy_hold_nav(code):
    """满仓持有单标的净值"""
    c0 = CLOSE[code][DATES[0]]
    return [CLOSE[code][d]/c0 for d in DATES]

# ===== 定义要对比的策略 =====
strategies = [
    {"name": "原策略 MA20·周频·20日动量·TOP3", "fn": lambda: backtest_nav(20, 'weekly', 20, 3, True)},
    {"name": "最优版 年线止损·周频·250日动量·TOP3", "fn": lambda: backtest_nav(250, 'weekly', 250, 3, True)},
    {"name": "无止损·双周·20日动量·TOP2", "fn": lambda: backtest_nav(0, 'biweekly', 20, 2, True)},
    {"name": "满仓纳指（基准）", "fn": lambda: buy_hold_nav('513100')},
    {"name": "满仓沪深300（基准）", "fn": lambda: buy_hold_nav('510300')},
]

result = {
    "dates": DATES,
    "strategies": []
}

for s in strategies:
    navs = s["fn"]()
    ann, mdd, sharpe = stats(navs)
    total_ret = (navs[-1]/navs[0]-1)*100
    mdd_pct, peak_idx, trough_idx = compute_mdd(navs)
    # 总资产（300万本金）
    totals = [round(v*CAPITAL) for v in navs]
    result["strategies"].append({
        "name": s["name"],
        "nav": [round(v,4) for v in navs],
        "total": totals,
        "ann": round(ann,2),
        "mdd": round(mdd_pct,2),
        "sharpe": round(sharpe,2),
        "total_ret": round(total_ret,2),
        "mdd_peak_idx": peak_idx,
        "mdd_trough_idx": trough_idx,
        "mdd_peak_date": DATES[peak_idx],
        "mdd_trough_date": DATES[trough_idx],
        "final_total": totals[-1],
    })
    print(f"{s['name']}: 年化{ann:.2f}% 回撤{mdd_pct:.2f}% 夏普{sharpe:.2f} 累计{total_ret:.2f}% 期末{totals[-1]/1e4:.0f}万")

json.dump(result, open("backtest_data/curve_compare.json","w"), ensure_ascii=False)
print("\n✅ 保存 curve_compare.json")
