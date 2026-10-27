#!/usr/bin/env python3
"""十年十倍复利策略 · v4（波动率目标·长窗口版）· 300万 · 2016-01-01 起

在 v3 基础上，把「波动率目标的窗口」从 20 日拉长到 40 日。
  无止损 · 双周调仓 · 20日动量 · TOP2 · 波动过滤(>2%剔除) · 波动率目标15%·40日窗

目的：解决 v3 在震荡市（2026年）追涨杀跌的软肋。
  40日窗让波动率目标更"钝"，不因短期波动反复降仓/加仓，震荡市更稳。

结果：年化 18.91% ｜ 回撤 -16.67% ｜ 夏普 1.15 ｜ 卡玛 1.135 ｜ 2026 +9.05%
输出结构与 v3 一致，供 gen_data.py 读取。
"""
import json, os
import statistics
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "backtest_data", "prices_10y_open.json")
OUT = os.path.join(BASE, "backtest_data", "sim_10y_v4.json")

ETFS = [("510300","沪深300"),("159915","创业板"),("513100","纳指"),("513500","标普500"),("518880","黄金")]
NAMES = [c for c,_ in ETFS]
LABEL = {c:n for c,n in ETFS}

CAPITAL = 3_000_000
MD = 20           # 动量窗口：20日
VOL_N = 20        # 个股波动过滤窗口：20日
VOL_LIMIT = 0.02  # 个股波动过滤：>2% 剔除
TOP_K = 2
COST = 0.0008
START = "2016-01-01"

VOL_TARGET = 0.15   # 目标年化波动 15%
VOL_WIN = 40        # 组合净值波动计算窗口：40日（v4 关键改动）

ANNF = 244 ** 0.5


def is_friday(d):
    return datetime.strptime(d, "%Y-%m-%d").weekday() == 4


def is_biweekly_rebalance(i):
    d = DATES[i]
    return is_friday(d) and (i // 5) % 2 == 0


def main():
    global DATES
    data = json.load(open(DATA))
    date_sets = [set(d for d,_ in data[n]) for n in NAMES]
    DATES = sorted(set.intersection(*date_sets))
    DATES = [d for d in DATES if d >= START]
    close = {n:{d:v[1] for d,v in data[n]} for n in NAMES}
    openp = {n:{d:v[0] for d,v in data[n]} for n in NAMES}
    print(f"回放区间 {DATES[0]} ~ {DATES[-1]}，{len(DATES)} 交易日")

    holdings = {}
    cash = CAPITAL
    nav_series = []; hold_series = []; trade_log = []
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
                    p = openp[c][d]
                    cash += h["shares"]*p*(1-COST)
                    trade_log.append({"date":d,"action":"卖出","code":c,"label":LABEL[c],
                                      "shares":h["shares"],"price":round(p,3),
                                      "amount":round(h["shares"]*p*(1-COST),0)})
            for c in target:
                p = openp[c][d]
                cur_sh = holdings.get(c, {}).get("shares", 0)
                cur_v = cur_sh * p
                diff = each - cur_v
                if diff > p:
                    sh = int(diff/(p*(1+COST)))//100*100
                    if sh > 0:
                        old_sh = holdings.get(c, {}).get("shares",0)
                        old_cost = holdings.get(c, {}).get("cost",0)
                        total_sh = old_sh + sh
                        new_cost = (old_sh*old_cost + sh*p)/total_sh if total_sh>0 else p
                        holdings[c] = {"shares":total_sh, "cost":new_cost}
                        cash -= sh*p*(1+COST)
                        trade_log.append({"date":d,"action":"买入","code":c,"label":LABEL[c],
                                          "shares":sh,"price":round(p,3),
                                          "amount":round(sh*p*(1+COST),0)})
                elif diff < -p:
                    sh = min(cur_sh, int((-diff)/(p*(1-COST)))//100*100)
                    if sh > 0:
                        new_sh = cur_sh - sh
                        cash += sh*p*(1-COST)
                        if new_sh > 0:
                            holdings[c]["shares"] = new_sh
                        else:
                            holdings.pop(c, None)
                        trade_log.append({"date":d,"action":"减仓","code":c,"label":LABEL[c],
                                          "shares":sh,"price":round(p,3),
                                          "amount":round(sh*p*(1-COST),0)})
            pending = None

        if i >= MD and is_biweekly_rebalance(i):
            metrics = {}
            for n in NAMES:
                mom = close[n][d] / close[n][DATES[i-MD]] - 1
                rets = [close[n][DATES[j]]/close[n][DATES[j-1]]-1 for j in range(i-VOL_N+1,i+1)]
                m = sum(rets)/len(rets)
                vol = (sum((r-m)**2 for r in rets)/len(rets))**0.5
                metrics[n] = (mom, vol)
            ranked = sorted(NAMES, key=lambda n: metrics[n][0], reverse=True)
            target = [n for n in ranked[:TOP_K] if metrics[n][0] > 0 and metrics[n][1] <= VOL_LIMIT]

            nav_now = (cash + sum(h["shares"]*close[c][d] for c, h in holdings.items())) / CAPITAL
            combined = nav_arr + [nav_now]
            if len(combined) >= VOL_WIN + 1:
                rets = [combined[j]/combined[j-1]-1 for j in range(len(combined)-VOL_WIN, len(combined))]
                m = sum(rets)/len(rets)
                vol = (sum((r-m)**2 for r in rets)/len(rets))**0.5
                ann_vol = vol * ANNF
                scale = max(0.0, min(1.0, VOL_TARGET/ann_vol)) if ann_vol > 0 else 1.0
            else:
                scale = 1.0
            pending = (target, scale)

        mv = sum(h["shares"]*close[c][d] for c, h in holdings.items())
        total = cash + mv
        nav = total / CAPITAL
        nav_arr.append(nav)
        nav_series.append({"date":d, "nav":round(nav,6), "total":round(total,0),
                           "cash":round(cash,0), "market":round(mv,0)})
        hold_series.append({"date":d, "holds":{LABEL[c]: holdings[c]["shares"]*close[c][d] for c in holdings}})

    navs = [x["nav"] for x in nav_series]
    total_ret = (navs[-1]/navs[0]-1)*100
    days = len(navs); years = days/244
    ann = (navs[-1]/navs[0])**(1/years)-1
    peak = navs[0]; mdd = 0
    for v in navs:
        peak = max(peak, v); mdd = max(mdd, (peak-v)/peak)
    rets = [navs[i]/navs[i-1]-1 for i in range(1,len(navs))]
    sharpe = statistics.mean(rets)/statistics.pstdev(rets)*(244**0.5) if statistics.pstdev(rets)>0 else 0
    calmar = (ann*100)/(mdd*100) if mdd>0 else 0

    yearly = {}
    for x in nav_series:
        yearly.setdefault(x["date"][:4], []).append(x["nav"])
    year_ret = {y: round((yearly[y][-1]/yearly[y][0]-1)*100, 2) for y in sorted(yearly)}

    result = {
        "start": DATES[0], "end": DATES[-1], "capital": CAPITAL,
        "strategy": {"name":"复利动能轮动·波动率目标长窗版","ma":0,"freq":"biweekly","md":20,
                     "top_k":2,"vol_limit":0.02,"vol_target":VOL_TARGET,"vol_win":VOL_WIN},
        "nav_series": nav_series, "hold_series": hold_series, "trades": trade_log,
        "summary": {
            "total_ret": round(total_ret,2), "ann": round(ann*100,2),
            "mdd": round(mdd*100,2), "sharpe": round(sharpe,2), "calmar": round(calmar,3),
            "days": days, "trades": len(trade_log),
            "final_total": round(navs[-1]*CAPITAL,0),
            "year_ret": year_ret,
        }
    }
    json.dump(result, open(OUT,"w"), ensure_ascii=False)

    s = result["summary"]
    print(f"\n=== 300万 · 2016-2026 波动率目标长窗版（15%·40日）===")
    print(f"区间 {DATES[0]} ~ {DATES[-1]}，{days} 交易日，{years:.2f} 年")
    print(f"期末 ¥{s['final_total']:,.0f} ｜ 累计 {s['total_ret']:+.2f}% ｜ 年化 {s['ann']:+.2f}%")
    print(f"回撤 -{s['mdd']}% ｜ 夏普 {s['sharpe']} ｜ 卡玛 {s['calmar']} ｜ 交易 {s['trades']} 次")
    print("\n分年度收益：")
    for y, r in year_ret.items():
        print(f"  {y}: {r:+.2f}%")


if __name__ == "__main__":
    main()
