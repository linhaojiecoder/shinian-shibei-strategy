#!/usr/bin/env python3
"""扩充资产池扫描：9只ETF（原5只 + 上证50/恒生/医药/中概互联）
重点测最优参数方向：年线止损、250日动量、周频/双周频
"""
import json, os
from datetime import datetime
import statistics
from itertools import product

BASE = os.path.dirname(os.path.abspath(__file__))
main = json.load(open(os.path.join(BASE, "backtest_data/prices_10y_open.json")))
extra = json.load(open(os.path.join(BASE, "backtest_data/prices_extra_open.json")))

# 合并：原5只 + 可用的4只
ALL = {
    "510300": "沪深300", "159915": "创业板", "513100": "纳指",
    "513500": "标普500", "518880": "黄金",
    "510050": "上证50", "159920": "恒生", "512010": "医药", "513050": "中概互联",
}
data = {}
for code in ALL:
    if code in main:
        data[code] = main[code]
    elif code in extra:
        data[code] = extra[code]

NAMES = list(data.keys())
CAPITAL = 3_000_000
COST = 0.0008
START = "2016-01-01"

# 交集日期（513050 从 2017-01-18 才有，会让起始日期推迟，需要处理）
date_sets = [set(d for d,_ in data[n]) for n in NAMES]
DATES = sorted(set.intersection(*date_sets))
DATES = [d for d in DATES if d >= START]
print(f"交集交易日: {len(DATES)}天, {DATES[0]} ~ {DATES[-1]}")

CLOSE = {n:{d:v[1] for d,v in data[n] if d in set(DATES)} for n in NAMES}
OPENP = {n:{d:v[0] for d,v in data[n] if d in set(DATES)} for n in NAMES}

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

def stats(navs):
    years = len(navs)/244
    ann = ((navs[-1]/navs[0])**(1/years)-1)*100
    peak = navs[0]; mdd = 0
    for v in navs:
        peak = max(peak, v); mdd = max(mdd, (peak-v)/peak)
    rets = [navs[i]/navs[i-1]-1 for i in range(1,len(navs))]
    sharpe = statistics.mean(rets)/statistics.pstdev(rets)*(244**0.5) if statistics.pstdev(rets)>0 else 0
    calmar = ann/(mdd*100) if mdd>0 else 0
    return ann, mdd*100, sharpe, calmar

def backtest(ma_n, freq, md, top_k, vol_on):
    holdings = {}
    cash = CAPITAL
    nav_series = []
    trade_count = 0
    pending_target = None
    pending_stop = set()

    for i, d in enumerate(DATES):
        if i > 0 and (pending_target is not None or pending_stop):
            for code in list(pending_stop):
                if code in holdings:
                    h = holdings.pop(code)
                    p = OPENP[code][d]
                    cash += h["shares"] * p * (1 - COST); trade_count += 1
            if pending_target is not None:
                for code in list(holdings.keys()):
                    if code not in pending_target and code not in pending_stop:
                        h = holdings.pop(code)
                        p = OPENP[code][d]
                        cash += h["shares"]*p*(1-COST); trade_count += 1
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
                                cash -= sh*p*(1+COST); trade_count += 1
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

    return stats(nav_series) + (trade_count,)

if __name__ == "__main__":
    results = []
    ma_opts = [0, 120, 250]
    freq_opts = ['weekly', 'biweekly', 'monthly']
    md_opts = [20, 120, 250]
    topk_opts = [2, 3, 4]
    vol_opts = [True, False]

    total = len(ma_opts)*len(freq_opts)*len(md_opts)*len(topk_opts)*len(vol_opts)
    print(f"共 {total} 组，扫描中（9只ETF）...")

    for ma_n, freq, md, top_k, vol_on in product(ma_opts, freq_opts, md_opts, topk_opts, vol_opts):
        ann, mdd, sharpe, calmar, trades = backtest(ma_n, freq, md, top_k, vol_on)
        results.append({"ann":ann,"mdd":mdd,"sharpe":sharpe,"calmar":calmar,"trades":trades,
                        "ma":ma_n,"freq":freq,"md":md,"topk":top_k,"vol":vol_on})

    results.sort(key=lambda x: x["ann"], reverse=True)
    print("\n=== 年化 TOP 20（9只ETF池）===")
    for i,r in enumerate(results[:20]):
        print(f"{i+1:>2}. 年化{r['ann']:6.2f}% 回撤{r['mdd']:6.2f}% 夏普{r['sharpe']:.2f} 卡玛{r['calmar']:.2f} 交易{r['trades']:>4}  MA{r['ma']:>3} {r['freq']:<9} MD{r['md']:>3} TOP{r['topk']} 波动{'开' if r['vol'] else '关'}")

    results.sort(key=lambda x: x["calmar"], reverse=True)
    print("\n=== 卡玛 TOP 10 ===")
    for i,r in enumerate(results[:10]):
        print(f"{i+1:>2}. 卡玛{r['calmar']:.2f} 年化{r['ann']:6.2f}% 回撤{r['mdd']:6.2f}% 夏普{r['sharpe']:.2f}  MA{r['ma']:>3} {r['freq']:<9} MD{r['md']:>3} TOP{r['topk']} 波动{'开' if r['vol'] else '关'}")

    json.dump(results, open("backtest_data/scan3_results.json","w"), ensure_ascii=False)
    print("\n✅ 保存 scan3_results.json")
