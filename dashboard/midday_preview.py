#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
午盘预告 · 动量轮动策略
- 中午收盘后（11:30 后）用上午实时价算一次信号
- 输出：今天尾盘大概要买/卖什么，让你提前有底
- 只读，不修改任何持仓状态
"""
import json, subprocess, os
from datetime import datetime, date, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "..", "backtest_data")
PRICES_JSON = os.path.join(DATA_DIR, "prices.json")
STATE_JSON = os.path.join(BASE, "state.json")

ETFS = [
    ("510300", "sh510300", "沪深300"),
    ("159915", "sz159915", "创业板"),
    ("513100", "sh513100", "纳指"),
    ("513500", "sh513500", "标普500"),
    ("518880", "sh518880", "黄金"),
]
NAMES = [c for c, _, _ in ETFS]
LABEL = {c: n for c, _, n in ETFS}

CAPITAL = 3_000_000
MD = 20
MA_N = 20
VOL_N = 20
VOL_LIMIT = 0.02
TOP_K = 3
COST = 0.0008


def fetch(code, start, end):
    r = subprocess.run(
        ["westock", "kline", code, "--period", "day", "--start", start, "--end", end],
        capture_output=True, text=True, timeout=60,
    )
    return r.stdout


def parse(lines):
    rows = []
    for ln in lines.splitlines():
        ln = ln.strip()
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < 3 or cells[0] == "date" or "---" in cells[0]:
            continue
        try:
            rows.append((cells[0], float(cells[2])))
        except (ValueError, IndexError):
            continue
    return rows


def load_prices():
    """加载历史 + 拉取今日上午实时价"""
    data = {}
    if os.path.exists(PRICES_JSON):
        with open(PRICES_JSON) as f:
            data = json.load(f)
    today = date.today().isoformat()
    start = (date.today() - timedelta(days=120)).isoformat()
    for code, wcode, _ in ETFS:
        out = fetch(wcode, start, today)
        rows = parse(out)
        if code not in data:
            data[code] = rows
        else:
            merged = {d: v for d, v in data[code]}
            for d, v in rows:
                merged[d] = v
            data[code] = sorted(merged.items())
    return data


def stats_on(dates, px, i):
    out = {}
    for n in NAMES:
        if i < MD:
            out[n] = None
            continue
        mom = px[n][dates[i]] / px[n][dates[i - MD]] - 1
        ma20 = sum(px[n][dates[j]] for j in range(i - MA_N + 1, i + 1)) / MA_N
        rets = [px[n][dates[j]] / px[n][dates[j - 1]] - 1 for j in range(i - VOL_N + 1, i + 1)]
        m = sum(rets) / len(rets)
        vol = (sum((r - m) ** 2 for r in rets) / len(rets)) ** 0.5
        out[n] = {"price": px[n][dates[i]], "mom": mom, "ma20": ma20,
                  "vol": vol, "above": px[n][dates[i]] > ma20}
    return out


def load_state():
    if os.path.exists(STATE_JSON):
        with open(STATE_JSON) as f:
            return json.load(f)
    return {"cash": CAPITAL, "holdings": {}, "trades": []}


def main():
    print("午盘拉取实时行情...")
    data = load_prices()
    date_sets = [set(d for d, _ in data[n]) for n in NAMES]
    dates = sorted(set.intersection(*date_sets))
    px = {n: {d: v for d, v in data[n]} for n in NAMES}
    latest = dates[-1]

    i = len(dates) - 1
    metrics = stats_on(dates, px, i)
    ranked = sorted(NAMES, key=lambda n: metrics[n]["mom"], reverse=True)

    # 目标持仓（按当前实时价算）
    target = []
    for n in ranked[:TOP_K]:
        m = metrics[n]
        if m["mom"] > 0 and m["above"] and m["vol"] <= VOL_LIMIT:
            target.append(n)

    # 当前持仓
    state = load_state()
    cur_holds = set(state.get("holdings", {}).keys())

    # 生成买卖指令预览
    to_sell = [c for c in cur_holds if c not in target]
    to_buy = [c for c in target if c not in cur_holds]

    now = datetime.now().strftime("%H:%M")

    lines = []
    lines.append("📢 午盘预告 · 动量轮动（仅供尾盘参考）")
    lines.append(f"⏰ {date.today().isoformat()} {now} ｜ 数据：上午实时价")
    lines.append("")

    # 当前持仓
    if cur_holds:
        holds_str = "、".join(LABEL[c] for c in cur_holds)
    else:
        holds_str = "空仓（货基）"
    lines.append(f"当前持仓：{holds_str}")
    lines.append("")

    # 信号明细
    lines.append("—— 五标的信号（上午实时）——")
    for n in ranked:
        m = metrics[n]
        pass3 = n in target
        flag = "✅持有" if pass3 else "—"
        lines.append(f"{LABEL[n]:5s} 20日涨{m['mom']*100:+6.2f}%  波动{m['vol']*100:.2f}%  {'站上MA20' if m['above'] else '跌破MA20'}  {flag}")
    lines.append("")

    # 尾盘指令预告
    lines.append("—— 尾盘操作预告 ——")
    if not to_sell and not to_buy:
        lines.append("维持现状，无需调仓。")
    else:
        if to_sell:
            for c in to_sell:
                h = state["holdings"].get(c, {})
                sh = h.get("shares", 0)
                p = px[c][latest]
                amt = sh * p
                lines.append(f"🔴 拟卖出 {LABEL[c]}：{sh:,} 份 × {p:.3f} ≈ ¥{amt:,.0f}")
        if to_buy:
            # 估算买入金额：总资金等权
            market = sum(state["holdings"][c].get("shares", 0) * px[c][latest] for c in state["holdings"])
            total = state.get("cash", 0) + market
            each = total / len(target) if target else 0
            for c in to_buy:
                p = px[c][latest]
                sh = int(each / (p * (1 + COST)))
                sh = sh // 100 * 100
                amt = sh * p * (1 + COST)
                lines.append(f"🟢 拟买入 {LABEL[c]}：约 {sh:,} 份 × {p:.3f} ≈ ¥{amt:,.0f}")

    lines.append("")
    lines.append("⚠️ 预告基于上午价，尾盘可能变化，以收盘信号为准。")

    text = "\n".join(lines)
    print(text)
    return text


if __name__ == "__main__":
    main()
