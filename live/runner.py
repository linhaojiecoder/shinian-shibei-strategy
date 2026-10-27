# -*- coding: utf-8 -*-
"""
慢富十倍·复利策略 · 实盘跟踪主流程

流程（每个交易日 15:05 运行）：
  1. fetch_live 增量拉取 5 只 ETF 最新日线
  2. 读取实盘状态 state.json（持仓 + 现金 + 净值序列）
  3. 用信号引擎算当日信号（动量 TOP2 + 波动率目标 scale + 双周判定）
  4. 生成日报 / 调仓指令
  5. 推送企业微信机器人

首次使用：
  1. 编辑 live/config.json 填 webhook_url（企业微信群机器人地址）
  2. 编辑 state.json 填入你的初始本金（capital）与初始持仓（可选）
  3. 运行：python3 live/runner.py
"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import signal_engine as se
import fetch_live

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
CONFIG_FILE = os.path.join(BASE, "config.json")
STATE_FILE = os.path.join(BASE, "state.json")
LIVE_FILE = os.path.join(ROOT, "live", "prices_live.json")

# 交易成本（与回测一致）
COST = 0.0008
# A股 ETF 每手 100 份
LOT = 100


def load_json(path, default):
    if os.path.exists(path):
        return json.load(open(path))
    return default


def load_config():
    cfg = load_json(CONFIG_FILE, {})
    return cfg


def load_state():
    return load_json(STATE_FILE, {
        "capital": 3_000_000,          # 初始本金
        "cash": 3_000_000,             # 当前现金
        "holdings": {},                # code -> {"shares":int, "cost":float}
        "nav_arr": [],                 # 组合净值序列（用于波动率目标）
        "last_signal_date": None,
    })


def save_state(st):
    os.makedirs(BASE, exist_ok=True)
    json.dump(st, open(STATE_FILE, "w"), ensure_ascii=False, indent=2)


def build_close_map(data):
    """把 [{date,[open,close]}...] 转成 {date: close}，取完整序列。"""
    return {n: [(d, v[1]) for d, v in data[n]] for n in se.NAMES}


def current_nav(st, close_on_date):
    """按当日收盘价算当前总资产 / 初始本金 = 净值。"""
    mv = sum(st["holdings"].get(c, {}).get("shares", 0) * close_on_date.get(c, 0)
             for c in se.NAMES)
    return (st["cash"] + mv) / st["capital"]


def compute_target_shares(st, signal, openp):
    """由信号算目标股数（整手），返回 {code: 目标股数} 与目标现金占比说明。

    openp: 下一交易日开盘价（实际成交价）。这里用「当日收盘价」近似作为成交价参考，
    实盘你在下一开盘手动成交即可。
    """
    target = signal["target"]
    scale = signal["scale"]
    total = st["cash"] + sum(h.get("shares", 0) * openp.get(c, 0)
                             for c, h in st["holdings"].items())
    n = len(target)
    each = total * scale / n if n > 0 else 0.0
    plan = {}
    for c in target:
        p = openp.get(c, 0)
        if p <= 0:
            continue
        plan[c] = int(each / p) // LOT * LOT
    return plan, each, total, scale


def format_report(st, signal, data):
    """生成 markdown 日报/调仓指令文本。"""
    latest = signal["date"]
    close_on = {n: dict((d, v[1]) for d, v in data[n])[latest] for n in se.NAMES}
    nav = current_nav(st, close_on)

    # 全量动量/波动明细
    mom_lines = "\n".join(
        f"  - {se.LABEL[n]}：动量 {signal['mom'][n]*100:+.2f}%｜日波动 {signal['vol'][n]*100:.2f}%"
        for n in se.NAMES
    )

    lines = []
    lines.append(f"## 慢富十倍 · 跟踪日报 {latest}")
    lines.append("")
    lines.append(f"**当前净值：{nav:.4f}**（本金 ¥{st['capital']:,.0f}）")
    lines.append(f"现金：¥{st['cash']:,.0f}")

    holds = st["holdings"]
    if holds:
        lines.append("")
        lines.append("**当前持仓：**")
        for c, h in holds.items():
            p = close_on.get(c, 0)
            v = h["shares"] * p
            lines.append(f"  - {se.LABEL[c]}（{c}）：{h['shares']} 份 × ¥{p:.3f} ≈ ¥{v:,.0f}")
    else:
        lines.append("**当前持仓：空仓**")

    lines.append("")
    lines.append("**信号（20日动量 TOP2）：**")
    lines.append(mom_lines)
    lines.append(f"目标总仓位 scale = **{signal['scale']*100:.0f}%**")
    if signal["note"]:
        lines.append(f"⚠️ {signal['note']}")

    # 调仓日 vs 非调仓日
    if signal["is_rebalance"] and signal["target"]:
        # 用当日收盘价近似成交价，给出操作指令
        plan, each, total, scale = compute_target_shares(st, signal, close_on)
        lines.append("")
        lines.append("### 📌 今日为双周调仓日，操作指令如下：")
        # 卖出：不在 target 内的持仓
        for c in list(holds):
            if c not in signal["target"]:
                lines.append(f"  - 🔴 卖出 {se.LABEL[c]}（{c}）全部 {holds[c]['shares']} 份")
        # 调整到目标
        for c in signal["target"]:
            cur = holds.get(c, {}).get("shares", 0)
            tgt = plan.get(c, 0)
            if tgt > cur:
                lines.append(f"  - 🟢 买入 {se.LABEL[c]}（{c}）{tgt - cur} 份（至 {tgt} 份）")
            elif tgt < cur:
                lines.append(f"  - 🔴 减仓 {se.LABEL[c]}（{c}）{cur - tgt} 份（至 {tgt} 份）")
            else:
                lines.append(f"  - ⚪ 持有 {se.LABEL[c]}（{c}）不变（{cur} 份）")
        lines.append(f"\n目标每标的大约 ¥{each:,.0f}（总仓位 {scale*100:.0f}%）")
    elif signal["is_rebalance"] and not signal["target"]:
        lines.append("")
        lines.append("### 📌 今日为调仓日，但无标的通过过滤 → 应空仓（卖出全部持仓）")
        if holds:
            for c in list(holds):
                lines.append(f"  - 🔴 卖出 {se.LABEL[c]}（{c}）全部 {holds[c]['shares']} 份")
    else:
        lines.append("")
        lines.append("**非调仓日，持仓不变。**")

    lines.append("")
    lines.append("---")
    lines.append("_仅供参考，不构成投资建议。_")
    return "\n".join(lines)


def main():
    # 1. 拉数据
    print("== 拉取最新行情 ==")
    fetch_live.main()

    data = json.load(open(LIVE_FILE))
    close_map = build_close_map(data)
    close = {n: dict((d, v[1]) for d, v in data[n]) for n in se.NAMES}

    # 2. 读状态
    st = load_state()

    # 3. 算信号（scale 对齐回测：nav_arr(截至T-1) + 当日收盘 nav_now）
    #    对齐后的最新交易日
    date_sets = [set(d for d, _ in close_map[n]) for n in se.NAMES]
    common = sorted(set.intersection(*date_sets))
    if not common:
        print("无对齐交易日（数据不足），退出。")
        return
    latest = common[-1]

    # 当日收盘净值（用于 scale 的 combined = nav_arr + [nav_now]）
    close_on_latest = {n: close[n][latest] for n in se.NAMES}
    nav_now = current_nav(st, close_on_latest)

    signal = se.compute_signal(close_map, st["nav_arr"], nav_now=nav_now)
    if signal is None:
        print("无有效信号（数据不足），退出。")
        return

    # 4. 生成报告
    report = format_report(st, signal, data)
    print("\n" + report)

    # 5. 保存报告到本地
    os.makedirs(os.path.join(ROOT, "live", "reports"), exist_ok=True)
    report_path = os.path.join(ROOT, "live", "reports", f"{latest}.md")
    with open(report_path, "w") as f:
        f.write(report)

    # 6. 推送由 WorkBuddy 微信助理完成（自动化任务读取报告文件后发送），
    #    本脚本只负责：拉数据 → 算信号 → 生成报告文件 → 更新状态。

    # 7. 更新状态：记录净值（当日收盘净值 append 到 nav_arr）
    st["nav_arr"].append(nav_now)
    st["last_signal_date"] = latest
    save_state(st)
    print(f"\n状态已更新，净值 {nav_now:.4f}，nav_arr 长度 {len(st['nav_arr'])}")


if __name__ == "__main__":
    main()
