#!/usr/bin/env python3
"""慢富十倍·复利策略 · 复盘报告生成器
读 sim_v4.json + app_1.0/src/data.json，输出一份 Markdown 复盘 + 关键指标 JSON。
供 skill 复盘流程与定时自动化复用，保证口径一致、格式统一。
"""
import json, os, sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJ = "/Users/linhaojie/WorkBuddy/2026-10-12-21-59-24"

def load(p):
    return json.load(open(os.path.join(PROJ, p)))

def main():
    sim = load("backtest_data/sim_v4.json")
    cash = sim["cash_dividend"]  # 实盘口径：分红现金入账
    S = cash["summary"]
    last = cash["nav_series"][-1]
    latest_holdings = cash["hold_series"][-1].get("holdings", {})

    app = load("app_1.0/src/data.json")
    signals = app.get("signals", [])
    today_action = app.get("today_action", {})

    # 现价来自 data.json 的 signals（含最新不复权价）
    price_map = {s["name"]: s["price"] for s in signals}

    # 组装持仓明细
    holds_detail = []
    for label, h in latest_holdings.items():
        shares = h["shares"]
        cost = h["cost"]
        price = price_map.get(label)
        pnl_pct = round((price - cost) / cost * 100, 2) if (price and cost) else None
        holds_detail.append({
            "label": label, "shares": shares, "cost": cost,
            "price": price, "pnl_pct": pnl_pct,
        })

    report = {
        "date": last["date"],
        "summary": S,
        "latest": {
            "total": last["total"], "nav": last["nav"],
            "cash": last["cash"], "market": last["market"],
        },
        "holdings": holds_detail,
        "today_action": today_action,
        "signals": signals,
    }

    # 输出 JSON
    out_json = os.path.join(PROJ, "backtest_data", "review_latest.json")
    json.dump(report, open(out_json, "w"), ensure_ascii=False, indent=2)

    # 输出 Markdown 复盘
    lines = []
    lines.append(f"# 慢富十倍·复利策略 · 复盘 {last['date']}")
    lines.append("")
    lines.append("## 核心指标")
    lines.append("")
    lines.append(f"- 累计收益：**{S['total_ret']:+.2f}%**")
    lines.append(f"- 年化收益：{S['ann']:+.2f}%")
    lines.append(f"- 最大回撤：-{S['mdd']}%")
    lines.append(f"- 夏普比率：{S['sharpe']}")
    lines.append(f"- 期末总资产：¥{S['final_total']:,.0f}")
    lines.append("")
    lines.append("## 当前持仓")
    lines.append("")
    lines.append("| 标的 | 份额 | 成本价 | 现价 | 浮动盈亏 |")
    lines.append("|------|------|--------|------|----------|")
    for h in holds_detail:
        pnl = f"{h['pnl_pct']:+.2f}%" if h["pnl_pct"] is not None else "—"
        lines.append(f"| {h['label']} | {h['shares']:,.0f} | {h['cost']:.4f} | {h['price']} | {pnl} |")
    lines.append("")
    lines.append(f"现金：¥{last['cash']:,.0f} ｜ 持仓市值：¥{last['market']:,.0f}")
    lines.append("")
    lines.append(f"## 今日操作：{today_action.get('title', '—')}")
    lines.append("")
    lines.append(today_action.get("detail", ""))
    md = "\n".join(lines)

    out_md = os.path.join(PROJ, "backtest_data", "review_latest.md")
    with open(out_md, "w") as f:
        f.write(md)

    print(md)
    print(f"\n✅ 已写入 {out_json}")
    print(f"✅ 已写入 {out_md}")
    return report

if __name__ == "__main__":
    main()
