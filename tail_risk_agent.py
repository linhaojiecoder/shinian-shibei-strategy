#!/usr/bin/env python3
"""尾部风险保护机制探索 · 五标的动量轮动（300万 · 2016-01-01 起 · 无前视偏差）

基线：无止损 · 双周调仓 · 20日动量 · TOP2 · 波动率过滤(>2%剔除)
      年化 20.72% ｜ 回撤 -17.01% ｜ 夏普 1.13 ｜ 卡玛 1.219

测试机制：
  1) 组合级回撤止损（跌破峰值 X% 清仓，篮子站上 MA_N 再进场）
  2) 波动率目标（实际年化波动超过目标则按比例降仓）
  3) 分批止损（破短均线减半、破长均线清仓）
  4) 趋势确认再入场（入场需价格站上 MA_N）

成交：T 日收盘算信号，T+1 日开盘成交（OPENP）。单边成本 0.08%。
"""
import json, os
import statistics
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "backtest_data", "prices_10y_open.json")
OUT = os.path.join(BASE, "tail_risk_results.json")

ETFS = [("510300", "沪深300"), ("159915", "创业板"), ("513100", "纳指"),
        ("513500", "标普500"), ("518880", "黄金")]
NAMES = [c for c, _ in ETFS]
LABEL = {c: n for c, n in ETFS}

CAPITAL = 3_000_000
COST = 0.0008
START = "2016-01-01"
MD = 20
TOP_K = 2
VOL_LIMIT = 0.02
FREQ = "biweekly"

# ---------- 数据加载（对齐到交易日） ----------
raw = json.load(open(DATA))
date_sets = [set(d for d, _ in raw[n]) for n in NAMES]
DATES = sorted(set.intersection(*date_sets))
DATES = [d for d in DATES if d >= START]
N = len(DATES)

_close_d = {n: {d: v[1] for d, v in raw[n]} for n in NAMES}
_open_d = {n: {d: v[0] for d, v in raw[n]} for n in NAMES}
CLOSE = {n: [_close_d[n][d] for d in DATES] for n in NAMES}
OPEN = {n: [_open_d[n][d] for d in DATES] for n in NAMES}

# 等权篮子（归一化起点=1），用于组合级回撤再入场 & 波动率目标
BASKET = [sum(CLOSE[n][i] / CLOSE[n][0] for n in NAMES) / len(NAMES) for i in range(N)]


def ma_series(arr, w):
    out = [None] * len(arr)
    s = 0.0
    for i in range(len(arr)):
        s += arr[i]
        if i >= w:
            s -= arr[i - w]
        if i >= w - 1:
            out[i] = s / w
    return out


def vol_series(prices, w):
    """20日已实现日波动（总体标准差，与基线一致）"""
    out = [None] * len(prices)
    for i in range(w - 1, len(prices)):
        rets = [prices[j] / prices[j - 1] - 1 for j in range(i - w + 1, i + 1)]
        m = sum(rets) / w
        out[i] = (sum((r - m) ** 2 for r in rets) / w) ** 0.5
    return out


BMA = {w: ma_series(BASKET, w) for w in (10, 20, 60, 120)}
BVOL = {w: vol_series(BASKET, w) for w in (10, 20, 40)}   # 篮子日波动
CMA = {w: {n: ma_series(CLOSE[n], w) for n in NAMES} for w in (10, 20, 40, 60, 120)}
CVOL20 = {n: vol_series(CLOSE[n], 20) for n in NAMES}
ANNF = 244 ** 0.5


def is_friday(d):
    return datetime.strptime(d, "%Y-%m-%d").weekday() == 4


def is_rebalance_day(i):
    d = DATES[i]
    if FREQ == "weekly":
        return is_friday(d)
    if FREQ == "biweekly":
        return is_friday(d) and (i // 5) % 2 == 0
    if FREQ == "monthly":
        return d[5:7] != DATES[i - 1][5:7] if i > 0 else False
    return False


def momentum_target(i, entry_ma=None):
    """20日动量 TOP2 + 波动率过滤 + （可选）趋势入场过滤"""
    ranked = sorted(NAMES, key=lambda n: CLOSE[n][i] / CLOSE[n][i - MD] - 1, reverse=True)
    target = []
    for n in ranked[:TOP_K]:
        mom = CLOSE[n][i] / CLOSE[n][i - MD] - 1
        if mom <= 0:
            continue
        v = CVOL20[n][i]
        if v is not None and v > VOL_LIMIT:
            continue
        if entry_ma is not None:
            ma_v = CMA[entry_ma][n][i]
            if ma_v is None or CLOSE[n][i] <= ma_v:
                continue
        target.append(n)
    return target


def vol_exposure(i, vol_target, vol_win=20):
    """波动率目标：篮子年化波动超目标则降仓"""
    dv = BVOL[vol_win][i]
    if dv is None or dv <= 0:
        return 1.0
    realized_ann = dv * ANNF
    return min(1.0, vol_target / realized_ann)


def run(cfg):
    md = cfg.get("md", MD)
    top_k = cfg.get("top_k", TOP_K)
    vol_limit = cfg.get("vol_limit", VOL_LIMIT)
    dd_stop = cfg.get("dd_stop", None)          # 组合级回撤止损阈值
    reentry_ma = cfg.get("reentry_ma", None)     # 回撤后重新进场所需篮子均线
    vol_target = cfg.get("vol_target", None)     # 波动率目标（年化）
    vol_win = cfg.get("vol_win", 20)             # 波动率计算窗口
    vol_band = cfg.get("vol_band", 0.03)         # 降仓触发带宽
    tier = cfg.get("tier", None)                 # (短均线, 长均线)
    entry_ma = cfg.get("entry_ma", None)         # 趋势确认入场

    holdings = {}        # code -> shares
    cash = CAPITAL
    trades = 0
    mode = "normal"      # normal / defensive
    target_codes = []
    exposure = 1.0
    halved = set()

    navs = []
    peak = 1.0

    pending_target = None
    pending_exposure = 1.0
    pending_sell = set()
    pending_halve = set()
    pending_reduce = None

    for i in range(N):
        # ===== 1) 次日开盘执行 pending =====
        if i > 0:
            for c in list(pending_halve):
                if c in holdings:
                    sh = holdings[c]
                    sell = (sh // 2) // 100 * 100
                    if sell > 0:
                        p = OPEN[c][i]
                        cash += sell * p * (1 - COST)
                        holdings[c] -= sell
                        trades += 1
                        if holdings[c] == 0:
                            del holdings[c]
            for c in list(pending_sell):
                if c in holdings:
                    sh = holdings.pop(c)
                    p = OPEN[c][i]
                    cash += sh * p * (1 - COST)
                    trades += 1
            if pending_reduce is not None and target_codes:
                # 波动率目标：按比例降仓
                invested = sum(holdings[c] * OPEN[c][i] for c in holdings)
                if invested > 0:
                    total = cash + invested
                    target_inv = total * pending_reduce
                    if target_inv < invested:
                        ratio = target_inv / invested
                        for c in list(holdings):
                            sh = holdings[c]
                            newsh = int(sh * ratio) // 100 * 100
                            if newsh < sh:
                                p = OPEN[c][i]
                                cash += (sh - newsh) * p * (1 - COST)
                                holdings[c] = newsh
                                trades += 1
                                if newsh == 0:
                                    del holdings[c]
                exposure = pending_reduce
                pending_reduce = None
            if pending_target is not None:
                for c in list(holdings):
                    if c not in pending_target:
                        sh = holdings.pop(c)
                        p = OPEN[c][i]
                        cash += sh * p * (1 - COST)
                        trades += 1
                if pending_target:
                    mv = sum(holdings[c] * OPEN[c][i] for c in holdings)
                    total = cash + mv
                    invest = total * pending_exposure
                    each = invest / len(pending_target)
                    for c in pending_target:
                        p = OPEN[c][i]
                        cur = holdings.get(c, 0)
                        diff = each - cur * p
                        if diff > p:
                            sh = int(diff / (p * (1 + COST))) // 100 * 100
                            if sh > 0:
                                holdings[c] = holdings.get(c, 0) + sh
                                cash -= sh * p * (1 + COST)
                                trades += 1
                target_codes = list(pending_target)
                exposure = pending_exposure
                halved = set()
                pending_target = None
            pending_sell = set()
            pending_halve = set()

        # ===== 2) 收盘净值 & 峰值 =====
        mv = sum(holdings[c] * CLOSE[c][i] for c in holdings)
        nav = (cash + mv) / CAPITAL
        peak = max(peak, nav)
        dd = (peak - nav) / peak
        navs.append(nav)

        # ===== 3) 收盘算信号（次日开盘执行） =====
        # 组合级回撤止损：状态切换
        if mode == "normal":
            if dd_stop is not None and dd >= dd_stop:
                mode = "defensive"
                pending_sell = set(holdings.keys())
                pending_target = None
                pending_reduce = None
                target_codes = []
                exposure = 0.0
                halved = set()
        elif mode == "defensive":
            if reentry_ma is not None:
                ma_v = BMA[reentry_ma][i]
                if ma_v is not None and BASKET[i] > ma_v:
                    mode = "normal"
                    pending_target = momentum_target(i, entry_ma)
                    pending_exposure = vol_exposure(i, vol_target, vol_win) if vol_target else 1.0

        # 周期调仓（normal）
        if mode == "normal" and i >= md and is_rebalance_day(i):
            pending_target = momentum_target(i, entry_ma)
            pending_exposure = vol_exposure(i, vol_target, vol_win) if vol_target else 1.0

        # 波动率目标：每日降仓（risk-off 快速）
        if mode == "normal" and vol_target is not None and target_codes:
            e_new = vol_exposure(i, vol_target, vol_win)
            if e_new < exposure - vol_band:
                pending_reduce = e_new

        # 分批止损（normal）
        if mode == "normal" and tier is not None:
            s_ma, l_ma = tier
            for c in list(holdings):
                short_v = CMA[s_ma][c][i]
                long_v = CMA[l_ma][c][i]
                if long_v is not None and CLOSE[c][i] < long_v:
                    pending_sell.add(c)
                    halved.discard(c)
                elif short_v is not None and CLOSE[c][i] < short_v:
                    if c not in halved:
                        pending_halve.add(c)
                        halved.add(c)
                else:
                    halved.discard(c)

    # ---------- 指标 ----------
    years = len(navs) / 244
    ann = ((navs[-1] / navs[0]) ** (1 / years) - 1) * 100
    pk = navs[0]
    mdd = 0.0
    for v in navs:
        pk = max(pk, v)
        mdd = max(mdd, (pk - v) / pk)
    rets = [navs[j] / navs[j - 1] - 1 for j in range(1, len(navs))]
    sharpe = statistics.mean(rets) / statistics.pstdev(rets) * ANNF if statistics.pstdev(rets) > 0 else 0.0
    calmar = ann / (mdd * 100) if mdd > 0 else 0.0
    return dict(ann=round(ann, 2), mdd=round(mdd * 100, 2), sharpe=round(sharpe, 2),
                calmar=round(calmar, 3), trades=trades, years=round(years, 2))


def fmt(r):
    return (f"年化 {r['ann']:>7.2f}% ｜ 回撤 -{r['mdd']:>6.2f}% ｜ "
            f"夏普 {r['sharpe']:>5.2f} ｜ 卡玛 {r['calmar']:>6.3f} ｜ 交易 {r['trades']:>4d}")


def main():
    configs = []
    # 基线
    configs.append(("基线(无止损·双周·20日·TOP2)", {}))
    # 机制1：组合级回撤止损
    for th in (0.08, 0.10, 0.12):
        for ma in (20, 60):
            configs.append((f"回撤止损 {int(th*100)}% → 篮子站上MA{ma}", dict(dd_stop=th, reentry_ma=ma)))
    # 机制2：波动率目标（精细网格 + 不同波动窗口）
    for vt in (0.10, 0.12, 0.13, 0.14, 0.15, 0.16, 0.18):
        configs.append((f"波动率目标 {int(vt*100)}%", dict(vol_target=vt)))
    for vt, vw in ((0.12, 10), (0.12, 40), (0.15, 10), (0.15, 40)):
        configs.append((f"波动率目标 {int(vt*100)}% 窗口{vw}", dict(vol_target=vt, vol_win=vw)))
    # 机制3：分批止损
    for s, l in ((10, 40), (20, 60), (20, 120)):
        configs.append((f"分批止损 短MA{s}/长MA{l}", dict(tier=(s, l))))
    # 机制4：趋势确认入场
    for ma in (20, 60, 120):
        configs.append((f"趋势入场 站上MA{ma}", dict(entry_ma=ma)))
    # 组合
    configs.append(("回撤10%+MA20 再入 + 波动目标12%", dict(dd_stop=0.10, reentry_ma=20, vol_target=0.12)))
    configs.append(("回撤10%+MA60 再入 + 波动目标12%", dict(dd_stop=0.10, reentry_ma=60, vol_target=0.12)))
    configs.append(("回撤10%+MA20 再入 + 趋势入场MA60", dict(dd_stop=0.10, reentry_ma=20, entry_ma=60)))
    configs.append(("波动目标12% + 趋势入场MA60", dict(vol_target=0.12, entry_ma=60)))
    configs.append(("回撤8%+MA20 + 分批止损20/60", dict(dd_stop=0.08, reentry_ma=20, tier=(20, 60))))
    configs.append(("回撤10%+MA20 + 波动目标12% + 趋势MA60",
                    dict(dd_stop=0.10, reentry_ma=20, vol_target=0.12, entry_ma=60)))
    configs.append(("波动目标15% + 趋势入场MA20", dict(vol_target=0.15, entry_ma=20)))
    # 宽松的“熔断式”回撤止损（大阈值 + 长均线再入），验证是否仅作极端保护有用
    for th in (0.18, 0.25):
        configs.append((f"熔断式回撤止损 {int(th*100)}% → MA120再入", dict(dd_stop=th, reentry_ma=120)))

    results = []
    for name, cfg in configs:
        r = run(cfg)
        r["name"] = name
        r["cfg"] = cfg
        results.append(r)

    print(f"回测区间 {DATES[0]} ~ {DATES[-1]}，{N} 交易日，{len(configs)} 个方案\n")
    print(f"{'方案':<46}{'年化':>8}{'回撤':>8}{'夏普':>7}{'卡玛':>7}{'交易':>6}")
    print("-" * 92)
    for r in results:
        print(f"{r['name']:<46}{r['ann']:>7.2f}%{-r['mdd']:>7.2f}%"
              f"{r['sharpe']:>7.2f}{r['calmar']:>7.3f}{r['trades']:>6d}")

    # 满足目标：回撤 ≤ -15%（mdd ≤ 15%）且年化 ≥ 18%
    good = [r for r in results if r["mdd"] <= 15.0 and r["ann"] >= 18.0]
    good.sort(key=lambda r: r["calmar"], reverse=True)
    print("\n" + "=" * 92)
    print("达标方案（回撤≤15% 且 年化≥18%），按卡玛排序：")
    print("=" * 92)
    for r in good[:10]:
        print(f"  {r['name']:<44}  {fmt(r)}")

    # 全部按卡玛排序，用于最终推荐
    results_sorted = sorted(results, key=lambda r: r["calmar"], reverse=True)
    print("\n全部方案按卡玛排序 TOP8：")
    for r in results_sorted[:8]:
        print(f"  {r['name']:<44}  {fmt(r)}")

    json.dump({"results": results, "good": good}, open(OUT, "w"), ensure_ascii=False, indent=2)
    print(f"\n结果已写入 {OUT}")


if __name__ == "__main__":
    main()
