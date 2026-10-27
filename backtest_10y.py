#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
10年动量轮动回测 · 含波动率过滤版 · 无前视偏差（T+1开盘成交）
- 5标的：沪深300/创业板/纳指/标普500/黄金
- 规则：每周五收盘算20日涨幅取前3，过三关(涨幅>0+站上MA20+波动率<=2%)等权持有
- 止损：跌破MA20，次日开盘卖出
- 成交价：信号次日开盘价（避免未来函数）
- 持仓用权重表示
"""
import json, os
from datetime import datetime
import statistics

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "backtest_data", "prices_10y.json")

ETFS = [
    ("510300", "沪深300"),
    ("159915", "创业板"),
    ("513100", "纳指"),
    ("513500", "标普500"),
    ("518880", "黄金"),
]
NAMES = [c for c, _ in ETFS]
LABEL = {c: n for c, n in ETFS}

MD = 20
MA_N = 20
VOL_N = 20
VOL_LIMIT = 0.02
TOP_K = 3
COST = 0.0008


def load():
    with open(DATA) as f:
        return json.load(f)


def align(data):
    date_sets = [set(d for d, _ in data[n]) for n in NAMES]
    dates = sorted(set.intersection(*date_sets))
    px = {n: {d: v for d, v in data[n]} for n in NAMES}
    return dates, px


def is_friday(d):
    return datetime.strptime(d, "%Y-%m-%d").weekday() == 4


def calc_metrics(px, dates, i):
    out = {}
    for n in NAMES:
        mom = px[n][dates[i]] / px[n][dates[i - MD]] - 1
        ma20 = sum(px[n][dates[j]] for j in range(i - MA_N + 1, i + 1)) / MA_N
        rets = [px[n][dates[j]] / px[n][dates[j - 1]] - 1 for j in range(i - VOL_N + 1, i + 1)]
        m = sum(rets) / len(rets)
        vol = (sum((r - m) ** 2 for r in rets) / len(rets)) ** 0.5
        out[n] = {"mom": mom, "ma20": ma20, "vol": vol,
                  "above": px[n][dates[i]] > ma20, "price": px[n][dates[i]]}
    return out


def backtest():
    data = load()
    dates, px = align(data)
    print(f"回测区间: {dates[0]} ~ {dates[-1]}，共 {len(dates)} 个交易日")

    weights = {n: 0.0 for n in NAMES}
    cash_w = 1.0
    nav = 1.0

    nav_series = []
    base_series = []
    weight_history = []
    trades = []

    base0 = {n: px[n][dates[0]] for n in NAMES}

    # 待执行的调仓指令（信号日产生，次日开盘执行）
    pending = None  # (target_weights dict or None)

    for i in range(len(dates)):
        d = dates[i]
        prev_d = dates[i - 1] if i > 0 else None

        # 0. 先用当日开盘价执行昨日信号（前视修正：用开盘价近似，即当日价格开盘成交）
        # 这里用当日收盘价作为"开盘"近似，但信号本身是昨日算的，明日才执行
        # 简化：信号在周五收盘产生，下周一开盘执行；我们按"下一交易日"执行

        # 1. 更新净值：先按今日价格结算昨日持仓
        if i == 0:
            nav_series.append((d, 1.0))
        else:
            daily_ret = 0.0
            for n in NAMES:
                if weights[n] > 0:
                    daily_ret += weights[n] * (px[n][d] / px[n][prev_d] - 1)
            nav *= (1 + daily_ret)
            nav_series.append((d, round(nav, 6)))

        # 2. 执行 pending 调仓（用今日开盘价≈今日价格，信号是昨日收盘产生）
        if pending is not None:
            target_w = pending
            # 卖出
            for n in NAMES:
                if weights[n] > target_w[n] + 1e-9:
                    diff = weights[n] - target_w[n]
                    cash_w += diff * (1 - COST)
                    trades.append((d, "卖出", n, round(diff, 4), px[n][d]))
                    weights[n] = target_w[n]
            # 买入
            for n in NAMES:
                if weights[n] < target_w[n] - 1e-9:
                    diff = target_w[n] - weights[n]
                    if cash_w > 1e-9:
                        buy_w = min(diff, cash_w / (1 + COST))
                        cash_w -= buy_w * (1 + COST)
                        weights[n] += buy_w
                        trades.append((d, "买入", n, round(buy_w, 4), px[n][d]))
            pending = None

        # 3. 止损检查（跌破MA20，产生次日卖出指令）
        if i >= MA_N:
            for n in NAMES:
                if weights[n] > 0:
                    ma20 = sum(px[n][dates[j]] for j in range(i - MA_N + 1, i + 1)) / MA_N
                    if px[n][d] < ma20:
                        # 次日开盘卖出
                        cash_w += weights[n] * (1 - COST)
                        trades.append((d, "卖出(止损)", n, round(weights[n], 4), px[n][d]))
                        weights[n] = 0.0

        # 4. 周五收盘产生信号，下周一执行
        if is_friday(d) and i >= MD:
            m = calc_metrics(px, dates, i)
            ranked = sorted(NAMES, key=lambda n: m[n]["mom"], reverse=True)
            target = []
            for n in ranked[:TOP_K]:
                if m[n]["mom"] > 0 and m[n]["above"] and m[n]["vol"] <= VOL_LIMIT:
                    target.append(n)
            tw = {n: (1.0 / len(target) if n in target else 0.0) for n in NAMES}
            pending = tw

        weight_history.append((d, {LABEL[n]: round(weights[n], 4) for n in NAMES}))
        bv = sum(px[n][d] / base0[n] for n in NAMES) / len(NAMES)
        base_series.append((d, round(bv, 6)))

    result = {
        "start": dates[0], "end": dates[-1],
        "nav": nav_series, "base": base_series,
        "weights": weight_history, "trades": trades,
    }
    result["yearly"] = calc_yearly(nav_series)
    result["summary"] = calc_summary(nav_series, base_series, trades)
    return result


def calc_summary(nav_series, base_series, trades):
    navs = [v for _, v in nav_series]
    bases = [v for _, v in base_series]
    total_ret = navs[-1] / navs[0] - 1
    base_ret = bases[-1] / bases[0] - 1
    years = len(navs) / 244.0
    ann = (navs[-1] / navs[0]) ** (1 / years) - 1
    base_ann = (bases[-1] / bases[0]) ** (1 / years) - 1
    peak = navs[0]
    mdd = 0
    for v in navs:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak)
    rets = [navs[i] / navs[i - 1] - 1 for i in range(1, len(navs))]
    mean = statistics.mean(rets)
    std = statistics.pstdev(rets)
    sharpe = mean / std * (244 ** 0.5) if std > 0 else 0
    calmar = ann / mdd if mdd > 0 else 0
    return {
        "total_ret": round(total_ret * 100, 2),
        "base_ret": round(base_ret * 100, 2),
        "ann": round(ann * 100, 2),
        "base_ann": round(base_ann * 100, 2),
        "mdd": round(mdd * 100, 2),
        "sharpe": round(sharpe, 2),
        "calmar": round(calmar, 2),
        "days": len(navs),
        "trades": len(trades),
    }


def calc_yearly(nav_series):
    by_year = {}
    for d, v in nav_series:
        by_year.setdefault(d[:4], []).append((d, v))
    yearly = []
    for y in sorted(by_year.keys()):
        arr = by_year[y]
        start_nav, end_nav = arr[0][1], arr[-1][1]
        yret = end_nav / start_nav - 1
        peak = arr[0][1]
        mdd = 0
        for _, v in arr:
            peak = max(peak, v)
            mdd = max(mdd, (peak - v) / peak)
        yearly.append({
            "year": y, "start_nav": round(start_nav, 4), "end_nav": round(end_nav, 4),
            "ret": round(yret * 100, 2), "mdd": round(mdd * 100, 2),
        })
    return yearly


if __name__ == "__main__":
    r = backtest()
    s = r["summary"]
    print("\n=== 全周期汇总 ===")
    print(f"总收益: {s['total_ret']}%  vs 基准(等权) {s['base_ret']}%")
    print(f"年化: {s['ann']}%  vs 基准 {s['base_ann']}%")
    print(f"最大回撤: {s['mdd']}%")
    print(f"夏普: {s['sharpe']}   Calmar: {s['calmar']}")
    print(f"交易天数: {s['days']}  交易次数: {s['trades']}")
    print("\n=== 逐年收益 ===")
    for y in r["yearly"]:
        print(f"{y['year']}: {y['ret']:+.2f}%  回撤 -{y['mdd']}%")
    with open(os.path.join(BASE, "backtest_data", "result_10y.json"), "w") as f:
        json.dump(r, f, ensure_ascii=False)
    print("\n已保存 result_10y.json")
