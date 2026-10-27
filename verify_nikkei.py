#!/usr/bin/env python3
"""日经ETF 513000 加入验证 · 严格对齐 sim_full_v3.py 逻辑
公平对比：统一 2019-07-01 起的共同时间窗（513000 上市 2019-06-25）
"""
import json, os, statistics
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "backtest_data", "prices_full_open.json")
NIKKEI = os.path.join(BASE, "backtest_data", "prices_513000.json")

CAPITAL = 3_000_000
MD = 20
VOL_N = 20
VOL_LIMIT = 0.02
TOP_K = 2
COST = 0.0008
START = "2019-07-01"
VOL_TARGET = 0.15
VOL_WIN = 20
ANNF = 244 ** 0.5

def is_friday(d):
    return datetime.strptime(d, "%Y-%m-%d").weekday() == 4

def load_data(include_nikkei):
    data = json.load(open(DATA))
    if include_nikkei:
        data["513000"] = [(d, v) for d, v in sorted(json.load(open(NIKKEI)).items())]
    return data

def run(universe):
    data = load_data(True)
    date_sets = [set(d for d, _ in data[n]) for n in universe]
    DATES = sorted(set.intersection(*date_sets))
    DATES = [d for d in DATES if d >= START]
    close = {n: {d: v[1] for d, v in data[n]} for n in universe}
    openp = {n: {d: v[0] for d, v in data[n]} for n in universe}

    holdings = {}
    cash = CAPITAL
    nav_arr = []
    pending = None

    for i, d in enumerate(DATES):
        if pending is not None:
            target, scale = pending
            total = cash + sum(h["shares"]*openp[c][d] for c, h in holdings.items())
            n = len(target)
            each = total*scale/n if n > 0 else 0.0
            for c in list(holdings):
                if c not in target:
                    h = holdings.pop(c)
                    cash += h["shares"]*openp[c][d]*(1-COST)
            for c in target:
                p = openp[c][d]
                cur_sh = holdings.get(c, {}).get("shares", 0)
                cur_v = cur_sh*p
                diff = each - cur_v
                if diff > p:
                    sh = int(diff/(p*(1+COST)))//100*100
                    if sh > 0:
                        old_sh = holdings.get(c, {}).get("shares", 0)
                        old_cost = holdings.get(c, {}).get("cost", 0)
                        total_sh = old_sh + sh
                        new_cost = (old_sh*old_cost + sh*p)/total_sh if total_sh > 0 else p
                        holdings[c] = {"shares": total_sh, "cost": new_cost}
                        cash -= sh*p*(1+COST)
                elif diff < -p:
                    sh = min(cur_sh, int((-diff)/(p*(1-COST)))//100*100)
                    if sh > 0:
                        new_sh = cur_sh - sh
                        cash += sh*p*(1-COST)
                        if new_sh > 0:
                            holdings[c]["shares"] = new_sh
                        else:
                            holdings.pop(c, None)
            pending = None

        if i >= MD and is_friday(d) and (i//5) % 2 == 0:
            metrics = {}
            for n in universe:
                mom = close[n][d]/close[n][DATES[i-MD]] - 1
                rets = [close[n][DATES[j]]/close[n][DATES[j-1]]-1 for j in range(i-VOL_N+1, i+1)]
                m = sum(rets)/len(rets)
                vol = (sum((r-m)**2 for r in rets)/len(rets))**0.5
                metrics[n] = (mom, vol)
            ranked = sorted(universe, key=lambda n: metrics[n][0], reverse=True)
            target = [n for n in ranked[:TOP_K] if metrics[n][0] > 0 and metrics[n][1] <= VOL_LIMIT]
            nav_now = (cash + sum(h["shares"]*close[c][d] for c, h in holdings.items())) / CAPITAL
            combined = nav_arr + [nav_now]
            if len(combined) >= VOL_WIN + 1:
                rets = [combined[j]/combined[j-1]-1 for j in range(len(combined)-VOL_WIN, len(combined))]
                m = sum(rets)/len(rets)
                vol = (sum((r-m)**2 for r in rets)/len(rets))**0.5
                ann_vol = vol*ANNF
                scale = max(0.0, min(1.0, VOL_TARGET/ann_vol)) if ann_vol > 0 else 1.0
            else:
                scale = 1.0
            pending = (target, scale)

        mv = sum(h["shares"]*close[c][d] for c, h in holdings.items())
        total = cash + mv
        nav_arr.append(total/CAPITAL)

    navs = nav_arr
    total_ret = (navs[-1]/navs[0]-1)*100
    years = len(navs)/244
    ann = (navs[-1]/navs[0])**(1/years)-1
    peak = navs[0]; mdd = 0
    for v in navs:
        peak = max(peak, v); mdd = max(mdd, (peak-v)/peak)
    rets = [navs[i]/navs[i-1]-1 for i in range(1, len(navs))]
    sharpe = statistics.mean(rets)/statistics.pstdev(rets)*(244**0.5) if statistics.pstdev(rets) > 0 else 0
    return navs[-1], total_ret, ann*100, mdd*100, sharpe, len(navs), DATES[0], DATES[-1]

if __name__ == "__main__":
    base5 = ["510300", "159915", "513100", "513500", "518880"]
    with_nikkei = base5 + ["513000"]
    print(f"统一回测窗口：{START} 起（513000 上市 2019-06-25）\n")
    print(f'{"情形":<20}{"最终净值":>9}{"累计收益%":>11}{"年化%":>8}{"最大回撤%":>10}{"夏普":>7}')
    for name, uni in [("5标的(基准)", base5), ("6标的(加日经)", with_nikkei)]:
        fn, tr, ann, mdd, sharpe, days, s, e = run(uni)
        print(f'{name:<20}{fn:>9.4f}{tr:>11.2f}{ann:>8.2f}{mdd:>10.2f}{sharpe:>7.2f}')
        print(f'   区间 {s} ~ {e}，{days} 交易日')
