#!/usr/bin/env python3
"""十年十倍复利策略 · 最优版（路线A）· 300万 · 2016-01-01 起完整回测（无前视偏差）

最终确定的最优参数（全场卡玛第一）：
  无止损 · 双周调仓 · 20日动量 · TOP2 · 波动过滤(>2%剔除)
  结果：年化 20.72% ｜ 回撤 -17.01% ｜ 夏普 1.13 ｜ 卡玛 1.219

逻辑：T日收盘算信号，T+1日开盘成交（消除前视偏差）。
"""
import json, os
from datetime import datetime
import statistics

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "backtest_data", "prices_10y_open.json")
OUT = os.path.join(BASE, "backtest_data", "sim_10y_v2.json")

ETFS = [("510300","沪深300"),("159915","创业板"),("513100","纳指"),("513500","标普500"),("518880","黄金")]
NAMES = [c for c,_ in ETFS]
LABEL = {c:n for c,n in ETFS}

CAPITAL = 3_000_000
MD = 20        # 动量窗口：20日
MA_N = 0       # 止损：无（0 表示不设止损）
VOL_N = 20     # 波动率窗口：20日
VOL_LIMIT = 0.02
TOP_K = 2      # 持仓数量：前2名
COST = 0.0008
START = "2016-01-01"

def is_friday(d):
    return datetime.strptime(d, "%Y-%m-%d").weekday() == 4

def is_biweekly_rebalance(i):
    """双周调仓：周五且每两周一次"""
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
    pending_target = None

    for i, d in enumerate(DATES):
        # 执行 pending 调仓（次日开盘成交）
        if i > 0 and pending_target is not None:
            for code in list(holdings.keys()):
                if code not in pending_target:
                    h = holdings.pop(code)
                    p = openp[code][d]
                    cash += h["shares"]*p*(1-COST)
                    trade_log.append({"date":d,"action":"卖出","code":code,"label":LABEL[code],
                                      "shares":h["shares"],"price":round(p,3),
                                      "amount":round(h["shares"]*p*(1-COST),0)})
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

        # 双周调仓信号
        if i >= MD and is_biweekly_rebalance(i):
            metrics = {}
            for n in NAMES:
                mom = close[n][d] / close[n][DATES[i-MD]] - 1
                rets = [close[n][DATES[j]]/close[n][DATES[j-1]]-1 for j in range(i-VOL_N+1,i+1)]
                m = sum(rets)/len(rets)
                vol = (sum((r-m)**2 for r in rets)/len(rets))**0.5
                metrics[n] = {"mom":mom, "vol":vol}
            ranked = sorted(NAMES, key=lambda n: metrics[n]["mom"], reverse=True)
            target = []
            for n in ranked[:TOP_K]:
                if metrics[n]["mom"] > 0 and metrics[n]["vol"] <= VOL_LIMIT:
                    target.append(n)
            pending_target = target

        # 记录净值
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
    calmar = (ann*100)/(mdd*100) if mdd>0 else 0

    # 分年度收益
    yearly = {}
    for x in nav_series:
        yearly.setdefault(x["date"][:4], []).append(x["nav"])
    year_ret = {y: round((yearly[y][-1]/yearly[y][0]-1)*100, 2) for y in sorted(yearly)}

    result = {
        "start": DATES[0], "end": DATES[-1], "capital": CAPITAL,
        "strategy": {"name":"复利动能轮动·最优版","ma":0,"freq":"biweekly","md":20,"top_k":2,"vol_limit":0.02},
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
    print(f"\n=== 300万 · 2016-2026 最优版（无止损·双周·20日·TOP2）===")
    print(f"区间 {DATES[0]} ~ {DATES[-1]}，{days} 交易日，{years:.2f} 年")
    print(f"期末 ¥{s['final_total']:,.0f} ｜ 累计 {s['total_ret']:+.2f}% ｜ 年化 {s['ann']:+.2f}%")
    print(f"回撤 -{s['mdd']}% ｜ 夏普 {s['sharpe']} ｜ 卡玛 {s['calmar']} ｜ 交易 {s['trades']} 次")
    print("\n分年度收益：")
    for y, r in year_ret.items():
        print(f"  {y}: {r:+.2f}%")

if __name__ == "__main__":
    main()
