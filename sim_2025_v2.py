#!/usr/bin/env python3
"""300万模拟盘 · 2025-01-01 回放（无前视偏差版）
关键修正：信号在 T 日收盘计算，成交在 T+1 日开盘价执行（实盘可实现）。
止损同样：T 日收盘确认跌破 MA20，T+1 日开盘卖出。
"""
import json, os
from datetime import datetime
import statistics

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "backtest_data", "prices_2025_open.json")
OUT = os.path.join(BASE, "backtest_data", "sim_2025.json")

ETFS = [("510300","沪深300"),("159915","创业板"),("513100","纳指"),("513500","标普500"),("518880","黄金")]
NAMES = [c for c,_ in ETFS]
LABEL = {c:n for c,n in ETFS}

CAPITAL = 3_000_000
MD = 20; MA_N = 20; VOL_N = 20; VOL_LIMIT = 0.02; TOP_K = 3; COST = 0.0008

def load():
    return json.load(open(DATA))

def is_friday(d):
    return datetime.strptime(d, "%Y-%m-%d").weekday() == 4

def main():
    data = load()
    date_sets = [set(d for d,_ in data[n]) for n in NAMES]
    dates = sorted(set.intersection(*date_sets))
    dates = [d for d in dates if d >= "2025-01-01"]
    # close/open 字典
    close = {n:{d:(v[1]) for d,v in data[n]} for n in NAMES}
    openp = {n:{d:(v[0]) for d,v in data[n]} for n in NAMES}
    print(f"回放区间 {dates[0]} ~ {dates[-1]}，{len(dates)} 交易日")

    holdings = {}
    cash = CAPITAL
    nav_series = []; hold_series = []; trade_log = []

    # 待执行订单：T日收盘算信号，存到 pending，T+1 日开盘执行
    pending_target = None   # 周五调仓的 target 集合
    pending_stop = set()    # 需要止损的 code

    for i, d in enumerate(dates):
        # 0. 先执行 pending（用今日开盘价）
        if i > 0 and (pending_target is not None or pending_stop):
            # 止损卖出
            for code in list(pending_stop):
                if code in holdings:
                    h = holdings.pop(code)
                    p = openp[code][d]
                    cash += h["shares"] * p * (1 - COST)
                    trade_log.append({"date":d,"action":"卖出(止损)","code":code,"label":LABEL[code],
                                      "shares":h["shares"],"price":round(p,3),
                                      "amount":round(h["shares"]*p*(1-COST),0)})
            # 调仓卖出（不在 target 的）
            if pending_target is not None:
                for code in list(holdings.keys()):
                    if code not in pending_target and code not in pending_stop:
                        h = holdings.pop(code)
                        p = openp[code][d]
                        cash += h["shares"]*p*(1-COST)
                        trade_log.append({"date":d,"action":"卖出","code":code,"label":LABEL[code],
                                          "shares":h["shares"],"price":round(p,3),
                                          "amount":round(h["shares"]*p*(1-COST),0)})
                # 等权买入
                if pending_target:
                    mv = sum(holdings[c]["shares"]*openp[c][d] for c in holdings)
                    total = cash + mv
                    each = total / len(pending_target)
                    for code in pending_target:
                        p = openp[code][d]
                        cur_sh = holdings.get(code, {}).get("shares", 0)
                        cur_v = cur_sh * p
                        diff = each - cur_v
                        if diff > p:
                            sh = int(diff / (p*(1+COST))) // 100 * 100
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
            pending_target = None
            pending_stop = set()

        # 1. 每日止损信号（用今日收盘价判断，次日开盘执行）
        if i >= MA_N:
            for code in list(holdings.keys()):
                ma20 = sum(close[code][dates[j]] for j in range(i-MA_N+1, i+1)) / MA_N
                if close[code][d] < ma20:
                    pending_stop.add(code)

        # 2. 周五调仓信号（用今日收盘价算，次日开盘执行）
        if is_friday(d) and i >= MD:
            metrics = {}
            for n in NAMES:
                mom = close[n][d] / close[n][dates[i-MD]] - 1
                ma20 = sum(close[n][dates[j]] for j in range(i-MA_N+1,i+1)) / MA_N
                rets = [close[n][dates[j]]/close[n][dates[j-1]]-1 for j in range(i-VOL_N+1,i+1)]
                m = sum(rets)/len(rets)
                vol = (sum((r-m)**2 for r in rets)/len(rets))**0.5
                metrics[n] = {"mom":mom,"above":close[n][d]>ma20,"vol":vol}
            ranked = sorted(NAMES, key=lambda n: metrics[n]["mom"], reverse=True)
            target = []
            for n in ranked[:TOP_K]:
                if metrics[n]["mom"]>0 and metrics[n]["above"] and metrics[n]["vol"]<=VOL_LIMIT:
                    target.append(n)
            pending_target = target

        # 3. 记录净值（收盘价）
        mv = sum(holdings[c]["shares"]*close[c][d] for c in holdings)
        total = cash + mv
        nav = total / CAPITAL
        nav_series.append({"date":d, "nav":round(nav,6), "total":round(total,0),
                           "cash":round(cash,0), "market":round(mv,0)})
        hold_series.append({"date":d, "holds":{LABEL[c]: holdings[c]["shares"]*close[c][d] for c in holdings}})

    # 汇总
    navs = [x["nav"] for x in nav_series]
    total_ret = (navs[-1]/navs[0]-1)*100
    days = len(navs); years = days/244
    ann = (navs[-1]/navs[0])**(1/years)-1
    peak = navs[0]; mdd = 0
    for v in navs:
        peak = max(peak, v); mdd = max(mdd, (peak-v)/peak)
    rets = [navs[i]/navs[i-1]-1 for i in range(1,len(navs))]
    sharpe = statistics.mean(rets)/statistics.pstdev(rets)*(244**0.5) if statistics.pstdev(rets)>0 else 0

    result = {
        "start": dates[0], "end": dates[-1], "capital": CAPITAL,
        "nav_series": nav_series, "hold_series": hold_series, "trades": trade_log,
        "summary": {
            "total_ret": round(total_ret,2), "ann": round(ann*100,2),
            "mdd": round(mdd*100,2), "sharpe": round(sharpe,2),
            "days": days, "trades": len(trade_log),
            "final_total": round(navs[-1]*CAPITAL,0),
        }
    }
    json.dump(result, open(OUT,"w"), ensure_ascii=False)

    s = result["summary"]
    print(f"\n=== 300万 · 2025回放（次日开盘成交，无前视偏差）===")
    print(f"区间 {dates[0]} ~ {dates[-1]}")
    print(f"期末 ¥{s['final_total']:,.0f} ｜ 累计 {s['total_ret']:+.2f}% ｜ 年化 {s['ann']:+.2f}%")
    print(f"回撤 -{s['mdd']}% ｜ 夏普 {s['sharpe']} ｜ 交易 {s['trades']} 次")

if __name__ == "__main__":
    main()
