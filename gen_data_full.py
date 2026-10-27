#!/usr/bin/env python3
"""从 sim_v4.json（诚实版回测）生成 app_1.0/src/data.json
数据源：backtest_data/sim_v4.json（不复权真实价 + 份额拆分正确处理 + 分红现金入账）
"""
import json
from datetime import datetime

BASE = "backtest_data"
sim = json.load(open(f"{BASE}/sim_v4.json"))
cash = sim["cash_dividend"]  # 实盘口径：分红现金入账

S = cash["summary"]
nav_series = cash["nav_series"]
hold_series = cash["hold_series"]
trades = cash["trades"]

last = nav_series[-1]
latest_holds = hold_series[-1]["holds"]
# 精确期末持仓（份额 + 成本价），根治 continuity 从流水反推导致的跨拆分成本失真
latest_holdings = hold_series[-1].get("holdings", {})

# 月度收益
by_month = {}
for x in nav_series:
    by_month.setdefault(x["date"][:7], []).append(x["nav"])
monthly = [{"month": m, "ret": round((by_month[m][-1]/by_month[m][0]-1)*100, 2)} for m in sorted(by_month)]

# 信号（用真实不复权价算动量）
prices = json.load(open(f"{BASE}/prices_true_nofq.json"))
NAMES = [("510300", "沪深300ETF"), ("159915", "创业板ETF"), ("513100", "纳指ETF"),
         ("513500", "标普500ETF"), ("518880", "黄金ETF")]
dates = sorted(set.intersection(*[set(d for d, _ in prices[n]) for n, _ in NAMES]))
latest = dates[-1]
i = len(dates) - 1
close = {n: {d: v[1] for d, v in prices[n]} for n, _ in NAMES}
MD = VOL = 20

signals = []
for code, name in NAMES:
    mom = close[code][dates[i]] / close[code][dates[i-MD]] - 1
    rets = [close[code][dates[j]]/close[code][dates[j-1]]-1 for j in range(i-VOL+1, i+1)]
    m = sum(rets)/len(rets)
    vol = (sum((r-m)**2 for r in rets)/len(rets))**0.5
    pass_all = mom > 0 and vol <= 0.02
    signals.append({"name": name, "mom": round(mom*100, 2), "vol": round(vol*100, 2),
                    "pass": pass_all, "price": round(close[code][dates[i]], 3)})

passed = sorted([s for s in signals if s["pass"]], key=lambda s: -s["mom"])
buy_list = [s["name"] for s in passed[:2]]

# 当前实际持仓（从期末精确持仓取 label 列表）
current_hold_labels = list(latest_holdings.keys())  # 例如 ['标普500ETF', '纳指ETF']

is_friday = datetime.strptime(latest, "%Y-%m-%d").weekday() == 4
# 今日操作必须区分「是否持有」与「是否触发调仓」，不能说「空仓观望」——策略可能正持有着
if buy_list:
    action_type, action_title = "buy", "调仓买入"
    detail = "动量前2：" + "、".join(buy_list) + "，按波动率目标仓位买入，下个调仓日开盘执行"
elif current_hold_labels:
    action_type, action_title = "hold", "继续持有"
    detail = "当前持有：" + "、".join(current_hold_labels) + "。本调仓日未触发新标的，持仓不动"
else:
    action_type, action_title = "hold", "空仓观望"
    detail = "当前无持仓，且五标的均未通过筛选，继续空仓等待"

today_action = {
    "date": latest, "is_friday": is_friday, "type": action_type,
    "title": action_title, "buy": buy_list, "sell": [], "detail": detail,
}

# 沪深300 基准
hs300_close = close["510300"]
nav_dates = [x["date"] for x in nav_series]
base0 = hs300_close[nav_dates[0]]
hs300_series = [{"date": d, "nav": round(hs300_close[d]/base0, 6)} for d in nav_dates]

app_data = {
    "strategy_name": "慢富十倍·复利策略",
    "slogan": "慢慢变富，与时间为友",
    "data_version": 4,  # 数据版本号：成本/份额口径修复（精确持仓导出）。每次改数据口径 +1，触发 App 强制重接续
    "capital": 3000000,
    "start_date": "2014-01-02",
    "latest_date": last["date"],
    "summary": {
        "total_ret": S["total_ret"], "ann": S["ann"], "mdd": S["mdd"],
        "sharpe": S["sharpe"], "days": S["days"], "trades": S["trades"],
        "final_total": S["final_total"], "final_nav": round(last["nav"], 4),
        "year_ret": S.get("year_ret", {}),
    },
    "latest_state": {
        "total": last["total"], "nav": last["nav"], "cash": last["cash"],
        "market": last["market"], "holds_label": latest_holds,
        "holdings": latest_holdings,
    },
    "nav_series": nav_series,
    "hold_series": hold_series,
    "monthly": monthly,
    "trades": trades,
    "signals": signals,
    "today_action": today_action,
    "hs300_series": hs300_series,
    "_note": "诚实版回测：不复权真实价 + 份额拆分正确处理 + 分红现金入账口径",
}

json.dump(app_data, open("app_1.0/src/data.json", "w"), ensure_ascii=False)
print("✅ data.json 已更新（诚实版）")
print("   最新日期:", last["date"])
print("   期末总资产:", round(last["total"]))
print("   累计收益:", str(S["total_ret"]) + "%")
print("   年化:", str(S["ann"]) + "%", "回撤:", str(S["mdd"]) + "%", "夏普:", S["sharpe"])
print("   持仓:", latest_holds)
print("   今日操作:", action_title, "|", buy_list or "无")
