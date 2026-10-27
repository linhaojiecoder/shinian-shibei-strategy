# -*- coding: utf-8 -*-
"""
拉取 5 只 ETF 最新日线（westock CLI），增量合并到本地历史数据文件。

设计：
  - 本地保存一份「滚动历史」，供信号引擎计算动量/波动/净值。
  - 每次运行增量更新，用最新行情覆盖/追加，避免重复全量拉取。
  - QDII（513100/513500）盘中价格可能延迟，但收盘后 15:05 运行通常已更新；
    若发现最新日期落后 A 股，会在信号里体现（不强行造数据）。
"""
import json
import os
import subprocess
import time
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
DATA_FILE = os.path.join(ROOT, "backtest_data", "prices_full_open.json")
# 实盘运行用的滚动数据文件（与回测主数据分离，避免污染回测基准）
LIVE_FILE = os.path.join(ROOT, "live", "prices_live.json")

ETFS = {
    "510300": "sh510300",
    "159915": "sz159915",
    "513100": "sh513100",
    "513500": "sh513500",
    "518880": "sh518880",
}

# 增量拉取的起始日期：最近 45 个自然日足够覆盖 20 日动量 + 20 日波动 + 缓冲
LOOKBACK_DAYS = 45


def fetch_kline(code, start, end):
    """调用 westock kline，返回 {date: [open, close]}。"""
    r = subprocess.run(
        ["westock", "kline", code, "--period", "day", "--start", start, "--end", end],
        capture_output=True, text=True,
    )
    out = r.stdout
    rows = {}
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < 3:
            continue
        if cells[0] in ("date", "---") or "---" in cells[0]:
            continue
        try:
            date = cells[0]
            openp = float(cells[1])
            last = float(cells[2])
            rows[date] = [openp, last]
        except (ValueError, IndexError):
            continue
    return rows


def load_existing():
    """加载本地滚动数据；若不存在则从回测主数据初始化（含 2014-2015 历史）。"""
    if os.path.exists(LIVE_FILE):
        return json.load(open(LIVE_FILE))
    if os.path.exists(DATA_FILE):
        return json.load(open(DATA_FILE))
    return {c: [] for c in ETFS}


def main():
    today = datetime.now()
    end = today.strftime("%Y-%m-%d")
    start = (today - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    data = load_existing()

    for name, code in ETFS.items():
        rows = fetch_kline(code, start, end)
        # 合并：以 date 为键更新
        existing = {d: v for d, v in data.get(name, [])}
        existing.update(rows)
        data[name] = sorted(existing.items())
        latest = rows and max(rows) or "无"
        print(f"  {name}({code}): 增量 {len(rows)} 天, 最新 {latest}", flush=True)
        time.sleep(1.0)

    os.makedirs(os.path.dirname(LIVE_FILE), exist_ok=True)
    with open(LIVE_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False)

    # 打印最新交易日（对齐后）
    date_sets = [set(d for d, _ in data[n]) for n in ETFS]
    common = sorted(set.intersection(*date_sets))
    print(f"\n已保存 {LIVE_FILE}")
    print(f"对齐后最新交易日: {common[-1] if common else '无'}")
    for k in ETFS:
        last = data[k][-1]
        print(f"  {k}: {last[0]} 收 {last[1][1]}")


if __name__ == "__main__":
    main()
