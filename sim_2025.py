#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
300万模拟盘 · 2025-01-01 起回放执行
- 用真实历史数据，从 2025-01-01 开始按策略逐日执行到 2026-10-23
- 输出：完整净值曲线、逐日持仓、交易记录、月度/年度收益
- 策略口径与模拟盘一致：TOP3 + 三关 + 跌破MA20清仓
"""
import json, os
from datetime import datetime
import statistics

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "backtest_data", "prices_10y.json")
OUT = os.path.join(BASE, "backtest_data", "sim_2025.json")

ETFS = [("510300","沪深300"),("159915","创业板"),("513100","纳指"),("513500","标普500"),("518880","黄金")]
NAMES = [c for c,_ in ETFS]
LABEL = {c:n for c,n in ETFS}

CAPITAL = 3_000_000
MD = 20
MA_N = 20
VOL_N = 20
VOL_LIMIT = 0.02
TOP_K = 3
COST = 0.0008

def load():
    with open(DATA) as f:
        return json.load(f)

def is_friday(d):
    return datetime.strptime(d, "%Y-%m-%d").weekday() == 4

def main():
    data = load()
    date_sets = [set(d for d,_ in data[n]) for n in NAMES]
    dates = sorted(set.intersection(*date_sets))
    # 只保留 2025-01-01 之后
    dates = [d for d in dates if d >= "2025-01-01"]
    px = {n:{d:v for d,v in data[n]} for n in NAMES}
    print(f"回放区间 {dates[0]} ~ {dates[-1]}，{len(dates)} 交易日")

    # 份额制持仓，更贴近真实账户
    holdings = {}  # {code: {shares, cost}}
    cash = CAPITAL
    nav_series = []     # 每日净值
    hold_series = []    # 每日持仓市值
    trade_log = []      # 交易记录

    peak_nav = 1.0
    for i, d in enumerate(dates):
        # 1. 每日止损：跌破MA20清仓
        if i >= MA_N:
            for code in list(holdings.keys()):
                ma20 = sum(px[code][dates[j]] for j in range(i-MA_N+1, i+1)) / MA_N
                if px[code][d] < ma20:
                    h = holdings.pop(code)
                    p = px[code][d]
                    cash += h["shares"] * p * (1 - COST)
                    trade_log.append({"date":d,"action":"卖出(止损)","code":code,"label":LABEL[code],
                                      "shares":h["shares"],"price":round(p,3),
                                      "amount":round(h["shares"]*p*(1-COST),0)})

        # 2. 周五调仓
        if is_friday(d) and i >= MD:
            metrics = {}
            for n in NAMES:
                mom = px[n][d] / px[n][dates[i-MD]] - 1
                ma20 = sum(px[n][dates[j]] for j in range(i-MA_N+1,i+1)) / MA_N
                rets = [px[n][dates[j]]/px[n][dates[j-1]]-1 for j in range(i-VOL_N+1,i+1)]
                m = sum(rets)/len(rets)
                vol = (sum((r-m)**2 for r in rets)/len(rets))**0.5
                metrics[n] = {"mom":mom,"above":px[n][d]>ma20,"vol":vol}
            ranked = sorted(NAMES, key=lambda n: metrics[n]["mom"], reverse=True)
            target = []
            for n in ranked[:TOP_K]:
                if metrics[n]["mom"]>0 and metrics[n]["above"] and metrics[n]["vol"]<=VOL_LIMIT:
                    target.append(n)
            # 卖出不在target的
            for code in list(holdings.keys()):
                if code not in target:
                    h = holdings.pop(code)
                    p = px[code][d]
                    cash += h["shares"]*p*(1-COST)
                    trade_log.append({"date":d,"action":"卖出","code":code,"label":LABEL[code],
                                      "shares":h["shares"],"price":round(p,3),
                                      "amount":round(h["shares"]*p*(1-COST),0)})
            # 等权买入
            if target:
                mv = sum(holdings[c]["shares"]*px[c][d] for c in holdings)
                total = cash + mv
                each = total / len(target)
                for code in target:
                    p = px[code][d]
                    cur_sh = holdings.get(code, {}).get("shares", 0)
                    cur_v = cur_sh * p
                    diff = each - cur_v
                    if diff > p:
                        sh = int(diff / (p*(1+COST)))
                        sh = sh // 100 * 100
                        if sh > 0:
                            old_sh = holdings.get(code, {}).get("shares",0)
                            old_cost = holdings.get(code, {}).get("cost",0)
                            total_sh = old_sh + sh
                            new_cost = (old_sh*old_cost + sh*p)/total_sh if total_sh>0 else p
                            holdings[code] = {"shares":total_sh, "cost":new_cost}
                            cash -= sh*p*(1+COST)
                            trade_log.append({"date":d,"action":"买入","code":code,"label":LABEL[code],
                                              "shares":sh,"price":round(p,3),
                                              "amount":round(sh*p*(1+COST),0)})

        # 3. 记录净值
        mv = sum(holdings[c]["shares"]*px[c][d] for c in holdings)
        total = cash + mv
        nav = total / CAPITAL
        nav_series.append({"date":d, "nav":round(nav,6), "total":round(total,0),
                           "cash":round(cash,0), "market":round(mv,0)})
        hold_series.append({"date":d, "holds":{LABEL[c]: holdings[c]["shares"]*px[c][d] for c in holdings}})

    # 汇总
    navs = [x["nav"] for x in nav_series]
    total_ret = (navs[-1]/navs[0]-1)*100
    days = len(navs)
    years = days/244
    ann = (navs[-1]/navs[0])**(1/years)-1
    peak = navs[0]; mdd = 0
    for v in navs:
        peak = max(peak, v)
        mdd = max(mdd, (peak-v)/peak)
    rets = [navs[i]/navs[i-1]-1 for i in range(1,len(navs))]
    sharpe = statistics.mean(rets)/statistics.pstdev(rets)*(244**0.5) if statistics.pstdev(rets)>0 else 0

    result = {
        "start": dates[0], "end": dates[-1],
        "capital": CAPITAL,
        "nav_series": nav_series,
        "hold_series": hold_series,
        "trades": trade_log,
        "summary": {
            "total_ret": round(total_ret,2), "ann": round(ann*100,2),
            "mdd": round(mdd*100,2), "sharpe": round(sharpe,2),
            "days": days, "trades": len(trade_log),
            "final_total": round(navs[-1]*CAPITAL,0),
        }
    }
    json.dump(result, open(OUT,"w"), ensure_ascii=False)

    s = result["summary"]
    print(f"\n=== 300万模拟盘 · 2025-01-01 回放结果 ===")
    print(f"区间 {dates[0]} ~ {dates[-1]}")
    print(f"期末资产 ¥{s['final_total']:,.0f} ｜ 累计收益 {s['total_ret']:+.2f}% ｜ 年化 {s['ann']:+.2f}%")
    print(f"最大回撤 -{s['mdd']}% ｜ 夏普 {s['sharpe']} ｜ 交易 {s['trades']} 次")
    print(f"\n=== 月度收益 ===")
    by_month = {}
    for x in nav_series:
        m = x["date"][:7]
        by_month.setdefault(m, []).append(x["nav"])
    prev = 1.0
    for m in sorted(by_month):
        arr = by_month[m]
        r = (arr[-1]/arr[0]-1)*100
        print(f"{m}: {r:+.2f}%")
    return result

if __name__ == "__main__":
    main()
