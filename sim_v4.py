#!/usr/bin/env python3
"""慢富十倍·复利策略 · 诚实版回测（v4）
与 sim_full_v3.py 相同策略参数，但修正了数据口径的根本错误：
  1. 成交全部用「不复权真实价」（bfq），不用任何 qfq/hfq。
  2. 份额拆分日：同步反向调整持仓份额（总资产不变），正确处理纳指1:5、标普1:2。
  3. 现金分红：区分两套收益假设
     - 假设A「分红现金入账」：除息日现金划入账户，不自动再投（实盘真实口径）。
     - 假设B「分红再投入」：分红按除息日收盘价再买入（对应 qfq/hfq 的理论口径）。
  4. 动量/波动信号用「调整后的可比价序列」：在原始价上按事件表做后复权，保证比值正确。
     这一步是纯比值计算，不参与成交金额。

数据：backtest_data/prices_rebuild_nofq.json（分段拉取的不复权完整历史）
事件：backtest_data/events_table.json（权威公告核实）
输出：backtest_data/sim_v4.json（两套假设分别给出 summary）
"""
import json, os
import statistics
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "backtest_data", "prices_true_nofq.json")
EVENTS = os.path.join(BASE, "backtest_data", "events_table.json")
OUT = os.path.join(BASE, "backtest_data", "sim_v4.json")

ETFS = [("510300","沪深300ETF"),("159915","创业板ETF"),("513100","纳指ETF"),
        ("513500","标普500ETF"),("518880","黄金ETF")]
NAMES = [c for c,_ in ETFS]
LABEL = {c:n for c,n in ETFS}

CAPITAL = 3_000_000
MD = 20
VOL_N = 20
VOL_LIMIT = 0.02
TOP_K = 2
COST = 0.0008
START = "2014-01-01"
VOL_TARGET = 0.15
VOL_WIN = 20
ANNF = 244 ** 0.5


def is_friday(d):
    return datetime.strptime(d, "%Y-%m-%d").weekday() == 4


def build_adj_price(raw_prices, events, mode="hfq"):
    """在原始不复权价上，按事件表构造后复权（比值正确的可比价序列）。
    mode="hfq"：后复权（历史价乘以累积因子）。
    只用于动量/波动比值，不用于成交。
    """
    # raw_prices: {date: [open, close]}
    # 构建后复权因子，保证「比值正确」：
    #   - 拆分(1:N)：拆分日停牌，价格在下一交易日跳空下降 N 倍；
    #     后复权需把「拆分前的历史价」×N，才能与拆分后价格连续。
    #   - 现金分红(d元)：除息日价格跳空下降 d 元；
    #     后复权需把「除息前的历史价」按比例放大，保持连续。
    # 关键：事件公告日可能是停牌日，必须锚定到「价格实际跳空的那个交易日」。
    dates = sorted(raw_prices.keys())
    events_by_anchor = {}  # anchor_date -> [(type, val)]
    for e in events:
        raw_d = e["date"]
        # 找 >= raw_d 的第一个交易日作为锚点（价格跳空日）
        anchor = None
        for dd in dates:
            if dd >= raw_d:
                anchor = dd
                break
        if anchor is None:
            continue
        if e["type"] == "split":
            events_by_anchor.setdefault(anchor, []).append(("split", e["split_ratio"]))
        elif e["type"] == "cash_dividend":
            events_by_anchor.setdefault(anchor, []).append(("div", e["amount_per_share"]))

    # 从最新往前累乘：在锚点日「之前」（更早）的历史价需要放大
    cum = 1.0
    factor = {}
    for d in reversed(dates):
        factor[d] = cum
        if d in events_by_anchor:
            for typ, val in events_by_anchor[d]:
                if typ == "split":
                    cum *= val
                elif typ == "div":
                    close_d = raw_prices[d][1]
                    if close_d > 0:
                        ratio = (close_d + val) / close_d
                        cum *= ratio
    adj = {d: [raw_prices[d][0]*factor[d], raw_prices[d][1]*factor[d]] for d in dates}
    return adj


def run_backtest(mode="cash"):
    """mode: "cash"=分红现金入账, "reinvest"=分红再投入"""
    data = json.load(open(DATA))
    events = json.load(open(EVENTS))

    # 各标的：原始价 + 调整价（用于信号）
    raw = {}
    adj = {}
    for c in NAMES:
        arr = data[c]
        raw_map = {d: oc for d, oc in arr}
        raw[c] = raw_map
        evs = events.get(c, {}).get("events", [])
        adj[c] = build_adj_price(raw_map, evs, "hfq")

    date_sets = [set(raw[c].keys()) for c in NAMES]
    DATES = sorted(set.intersection(*date_sets))
    DATES = [d for d in DATES if d >= START]
    close_raw = {c: {d: raw[c][d][1] for d in raw[c]} for c in NAMES}
    open_raw = {c: {d: raw[c][d][0] for d in raw[c]} for c in NAMES}
    close_adj = {c: {d: adj[c][d][1] for d in adj[c]} for c in NAMES}

    holdings = {}   # code -> {"shares": float, "cost": float}
    cash = CAPITAL
    nav_series = []; hold_series = []; trade_log = []
    nav_arr = []
    pending = None

    # 预构建「拆分事件 → 触发交易日」映射。
    # 拆分公告日（如 2022-01-13）是停牌日，不在交易日序列里；
    # 拆分应生效在「拆分日之后的第一个交易日」（价格已跳空的那天，如 2022-01-14），
    # 且必须在当天开盘成交之前调整份额（否则市值凭空缩水 ratio 倍）。
    split_trigger = {}  # code -> {触发交易日: split_ratio}
    for c in NAMES:
        evs = events.get(c, {}).get("events", [])
        for e in evs:
            if e["type"] == "split":
                ed = e["date"]
                # 找 ed 之后（含）的第一个交易日
                trigger = next((dd for dd in DATES if dd >= ed), None)
                if trigger:
                    split_trigger.setdefault(c, {})[trigger] = e["split_ratio"]

    for i, d in enumerate(DATES):
        # 0) 份额拆分处理：在拆分后首个交易日、开盘成交前调整份额
        for c in NAMES:
            ratio = split_trigger.get(c, {}).get(d)
            if ratio and c in holdings:
                holdings[c]["shares"] *= ratio
                holdings[c]["cost"] /= ratio

        # 1) 执行 pending 信号（开盘成交）
        if pending is not None:
            target, scale = pending
            total = cash + sum(h["shares"]*open_raw[c].get(d, 0) for c, h in holdings.items())
            n = len(target)
            each = total*scale/n if n > 0 else 0.0
            for c in list(holdings):
                if c not in target:
                    h = holdings.pop(c)
                    p = open_raw[c].get(d, 0)
                    if p > 0:
                        cash += h["shares"]*p*(1-COST)
                        trade_log.append({"date": d, "action": "卖出", "code": c, "label": LABEL[c],
                                          "shares": h["shares"], "price": round(p, 3),
                                          "amount": round(h["shares"]*p*(1-COST), 0)})
            for c in target:
                p = open_raw[c].get(d, 0)
                if p <= 0:
                    continue
                cur_sh = holdings.get(c, {}).get("shares", 0)
                cur_v = cur_sh * p
                diff = each - cur_v
                if diff > p:
                    sh = int(diff/(p*(1+COST)))
                    if sh > 0:
                        old_sh = holdings.get(c, {}).get("shares", 0)
                        old_cost = holdings.get(c, {}).get("cost", 0)
                        total_sh = old_sh + sh
                        new_cost = (old_sh*old_cost + sh*p)/total_sh if total_sh > 0 else p
                        holdings[c] = {"shares": total_sh, "cost": new_cost}
                        cash -= sh*p*(1+COST)
                        trade_log.append({"date": d, "action": "买入", "code": c, "label": LABEL[c],
                                          "shares": sh, "price": round(p, 3),
                                          "amount": round(sh*p*(1+COST), 0)})
                elif diff < -p:
                    sh = min(cur_sh, int((-diff)/(p*(1-COST))))
                    if sh > 0:
                        new_sh = cur_sh - sh
                        cash += sh*p*(1-COST)
                        if new_sh > 0:
                            holdings[c]["shares"] = new_sh
                        else:
                            holdings.pop(c, None)
                        trade_log.append({"date": d, "action": "减仓", "code": c, "label": LABEL[c],
                                          "shares": sh, "price": round(p, 3),
                                          "amount": round(sh*p*(1-COST), 0)})
            pending = None

        # 2) 双周调仓信号（用调整价算动量/波动，比值正确）
        if i >= MD and is_friday(d) and (i//5) % 2 == 0:
            metrics = {}
            for c in NAMES:
                mom = close_adj[c][d] / close_adj[c][DATES[i-MD]] - 1
                rets = [close_adj[c][DATES[j]]/close_adj[c][DATES[j-1]]-1 for j in range(i-VOL_N+1, i+1)]
                m = sum(rets)/len(rets)
                vol = (sum((r-m)**2 for r in rets)/len(rets))**0.5
                metrics[c] = (mom, vol)
            ranked = sorted(NAMES, key=lambda c: metrics[c][0], reverse=True)
            target = [c for c in ranked[:TOP_K] if metrics[c][0] > 0 and metrics[c][1] <= VOL_LIMIT]

            nav_now = (cash + sum(h["shares"]*close_raw[c].get(d, 0) for c, h in holdings.items())) / CAPITAL
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

        # 3) 现金分红处理（除息日）
        for c in NAMES:
            evs = events.get(c, {}).get("events", [])
            for e in evs:
                if e["type"] == "cash_dividend" and e["date"] == d and c in holdings:
                    div_total = holdings[c]["shares"] * e["amount_per_share"]
                    if mode == "cash":
                        cash += div_total   # 现金入账
                    else:  # reinvest
                        p = close_raw[c].get(d, 0)
                        if p > 0:
                            sh = int(div_total/(p*(1+COST)))
                            if sh > 0:
                                holdings[c]["shares"] += sh
                                cash -= sh*p*(1+COST)

        # 4) 记录收盘净值
        mv = sum(h["shares"]*close_raw[c].get(d, 0) for c, h in holdings.items())
        total = cash + mv
        nav = total / CAPITAL
        nav_arr.append(nav)
        nav_series.append({"date": d, "nav": round(nav,6), "total": round(total,0),
                           "cash": round(cash,0), "market": round(mv,0)})
        # hold_series 同时记录「市值」（旧字段，兼容）与「精确份额 shares + 成本价 cost」（新字段，根治成本失真）
        hold_series.append({
            "date": d,
            "holds": {LABEL[c]: round(h["shares"]*close_raw[c].get(d,0),0) for c, h in holdings.items()},
            "holdings": {LABEL[c]: {"shares": h["shares"], "cost": round(h["cost"], 6)} for c, h in holdings.items()},
        })

    # 汇总
    navs = [x["nav"] for x in nav_series]
    total_ret = (navs[-1]/navs[0]-1)*100
    days = len(navs); years = days/244
    ann = (navs[-1]/navs[0])**(1/years)-1 if years > 0 else 0
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

    return {
        "mode": mode,
        "start": DATES[0], "end": DATES[-1], "capital": CAPITAL,
        "nav_series": nav_series, "hold_series": hold_series, "trades": trade_log,
        "summary": {
            "total_ret": round(total_ret,2), "ann": round(ann*100,2),
            "mdd": round(mdd*100,2), "sharpe": round(sharpe,2), "calmar": round(calmar,3),
            "days": days, "trades": len(trade_log), "final_total": round(navs[-1]*CAPITAL,0),
            "year_ret": year_ret,
        }
    }


if __name__ == "__main__":
    cash_result = run_backtest("cash")
    reinvest_result = run_backtest("reinvest")
    out = {
        "note": "诚实版回测：不复权真实价成交 + 份额拆分同步调整 + 两套分红假设",
        "cash_dividend": cash_result,
        "reinvest_dividend": reinvest_result,
    }
    json.dump(out, open(OUT, "w"), ensure_ascii=False)
    for name, r in [("分红现金入账", cash_result), ("分红再投入", reinvest_result)]:
        s = r["summary"]
        print(f"\n=== {name} ===")
        print(f"区间 {r['start']} ~ {r['end']}，{s['days']} 交易日")
        print(f"期末 ¥{s['final_total']:,.0f} ｜ 累计 {s['total_ret']:+.2f}% ｜ 年化 {s['ann']:+.2f}%")
        print(f"回撤 -{s['mdd']}% ｜ 夏普 {s['sharpe']} ｜ 卡玛 {s['calmar']}")
    print(f"\n✅ 已写入 {OUT}")
