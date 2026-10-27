#!/usr/bin/env python3
"""低相关资产扩充回测 · 降低五标的动量轮动策略最大回撤（v2，干净归因版）

引擎严格对齐 sim_10y_v2.py：T日收盘算信号 → T+1开盘成交，单边成本 0.08%，
起始 300 万，无止损，20日波动>2%剔除，动量>0 才入选。

归因方法（避免前视偏差 + 公平比较）：
  - 每个标的池用"自身成员的交集日期"作为回测窗口（不同标的上线时间/停牌缺口不同）
  - 加入某资产后，把"基线(5标的)"和"基线+新增"放在【同一窗口】跑，直接看增量效果
  - 两组报告：① 固定官方参数(TOP2/双周/20日) 纯看加资产的效果；② 各池最优参数(TOP_K×动量×调仓网格)

额外标的（prices_extra_open.json）:
  510050 上证50   2016-01-04 起，无缺口
  159920 恒生     2016-01-04 起，无缺口
  512010 医药     2016-01-04 起，有 246 天停牌缺口(散落)
  513050 中概互联 2017-01-18 起，无缺口
  (513030 德国 2023-12-29 截止 / 510880 红利 2025 起 → 数据窗太短，不纳入)
"""
import json, os, itertools, statistics
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(BASE, "backtest_data", "prices_10y_open.json")
EXTRA = os.path.join(BASE, "backtest_data", "prices_extra_open.json")
OUT = os.path.join(BASE, "backtest_data", "lowcorr_agent_result.json")

CAPITAL = 3_000_000
COST = 0.0008
VOL_N = 20
VOL_LIMIT = 0.02
START = "2016-01-01"
TRADING_DAYS = 244

BASE5 = ["510300", "159915", "513100", "513500", "518880"]
EXTRAS = ["510050", "159920", "512010", "513050"]
LABEL = {
    "510300": "沪深300", "159915": "创业板", "513100": "纳指",
    "513500": "标普500", "518880": "黄金",
    "510050": "上证50", "159920": "恒生", "512010": "医药", "513050": "中概互联",
}


def load_all():
    data = {}
    for path in (MAIN, EXTRA):
        for code, arr in json.load(open(path)).items():
            data[code] = arr
    return data


def build_window(data, codes, start=START):
    sets = [set(d for d, _ in data[c]) for c in codes]
    common = sorted(set.intersection(*sets))
    return [d for d in common if d >= start]


def precompute(data, codes, dates):
    idx = {d: i for i, d in enumerate(dates)}
    n = len(dates)
    close = {c: [None] * n for c in codes}
    openp = {c: [None] * n for c in codes}
    for c in codes:
        for d, (o, cl) in data[c]:
            if d in idx:
                i = idx[d]
                close[c][i] = cl
                openp[c][i] = o
    vol = {c: [0.0] * n for c in codes}
    for c in codes:
        for i in range(VOL_N, n):
            rets = [close[c][j] / close[c][j - 1] - 1 for j in range(i - VOL_N + 1, i + 1)]
            m = sum(rets) / len(rets)
            vol[c][i] = (sum((r - m) ** 2 for r in rets) / len(rets)) ** 0.5
    mds = [20, 60, 120, 250]
    mom = {md: {c: [0.0] * n for c in codes} for md in mds}
    for md in mds:
        for c in codes:
            for i in range(md, n):
                mom[md][c][i] = close[c][i] / close[c][i - md] - 1
    return close, openp, vol, mom


def is_biweekly(i, dates):
    return datetime.strptime(dates[i], "%Y-%m-%d").weekday() == 4 and (i // 5) % 2 == 0


def is_monthly(i, dates):
    return i == 0 or dates[i][:7] != dates[i - 1][:7]


def run_backtest(codes, dates, close, openp, vol, mom, top_k, md, freq):
    n = len(dates)
    schedule = is_biweekly if freq == "biweekly" else is_monthly
    holdings, cash, pending, trades, navs = {}, CAPITAL, None, 0, []
    for i in range(n):
        if i > 0 and pending is not None:
            for c in list(holdings.keys()):
                if c not in pending:
                    cash += holdings.pop(c) * openp[c][i] * (1 - COST)
                    trades += 1
            if pending:
                total = cash + sum(holdings[c] * openp[c][i] for c in holdings)
                each = total / len(pending)
                for c in pending:
                    p = openp[c][i]
                    diff = each - holdings.get(c, 0) * p
                    if diff > p:
                        sh = int(diff / (p * (1 + COST))) // 100 * 100
                        if sh > 0:
                            holdings[c] = holdings.get(c, 0) + sh
                            cash -= sh * p * (1 + COST)
                            trades += 1
            pending = None
        if i >= md and schedule(i, dates):
            ranked = sorted(codes, key=lambda c: mom[md][c][i], reverse=True)
            pending = [c for c in ranked[:top_k] if mom[md][c][i] > 0 and vol[c][i] <= VOL_LIMIT]
        cash_mv = sum(holdings[c] * close[c][i] for c in holdings)
        navs.append((cash + cash_mv) / CAPITAL)
    return summarize(navs, trades)


def summarize(navs, trades):
    if len(navs) < 2:
        return None
    days = len(navs)
    years = days / TRADING_DAYS
    ann = (navs[-1] / navs[0]) ** (1 / years) - 1
    peak, mdd = navs[0], 0.0
    for v in navs:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak)
    rets = [navs[i] / navs[i - 1] - 1 for i in range(1, len(navs))]
    sd = statistics.pstdev(rets)
    sharpe = statistics.mean(rets) / sd * (TRADING_DAYS ** 0.5) if sd > 0 else 0
    calmar = ann / mdd if mdd > 0 else 0
    return {"ann": ann * 100, "mdd": mdd * 100, "sharpe": sharpe,
            "calmar": calmar, "trades": trades, "total_ret": (navs[-1] / navs[0] - 1) * 100,
            "days": days, "years": round(years, 2)}


def grid(pool, dates, close, openp, vol, mom):
    """返回该池在给定窗口下所有 (top_k, md, freq) 配置的结果列表。"""
    out = []
    for top_k in [k for k in (2, 3, 4, 5) if k <= len(pool)]:
        for md in (20, 60, 120, 250):
            for freq in ("biweekly", "monthly"):
                s = run_backtest(pool, dates, close, openp, vol, mom, top_k, md, freq)
                if s:
                    out.append({"top_k": top_k, "md": md, "freq": freq, "s": s})
    return out


def best_by_calmar(results):
    return max(results, key=lambda r: r["s"]["calmar"])


def pick(results, top_k, md, freq):
    for r in results:
        if r["top_k"] == top_k and r["md"] == md and r["freq"] == freq:
            return r
    return None


def fmt_pool(pool):
    return "+".join(LABEL[c] for c in pool)


def main():
    data = load_all()

    # 0) 引擎校验
    db = build_window(data, BASE5)
    cl, op, vo, mo = precompute(data, BASE5, db)
    chk = run_backtest(BASE5, db, cl, op, vo, mo, 2, 20, "biweekly")
    print("=== 引擎校验：基线(5标的·2016起·双周·20日·TOP2) ===")
    print(f"  窗口 {db[0]}~{db[-1]} 年化 {chk['ann']:+.2f}% 回撤 -{chk['mdd']:.2f}% "
          f"夏普 {chk['sharpe']:.2f} 卡玛 {chk['calmar']:.3f}（官方:20.72/-17.01/1.13/1.219）\n")

    # 1) 基线自身最优（参考）
    base_grid = grid(BASE5, db, cl, op, vo, mo)
    base_best = best_by_calmar(base_grid)
    base_fixed = pick(base_grid, 2, 20, "biweekly")
    print("=== 基线(5标的,全窗口) 官方参数 vs 最优参数 ===")
    print(f"  官方TOP2/双周/20: 年化{base_fixed['s']['ann']:+.2f}% 回撤-{base_fixed['s']['mdd']:.2f}% "
          f"夏普{base_fixed['s']['sharpe']:.2f} 卡玛{base_fixed['s']['calmar']:.3f}")
    print(f"  最优({base_best['top_k']}/{base_best['freq']}/{base_best['md']}): "
          f"年化{base_best['s']['ann']:+.2f}% 回撤-{base_best['s']['mdd']:.2f}% "
          f"夏普{base_best['s']['sharpe']:.2f} 卡玛{base_best['s']['calmar']:.3f}\n")

    # 2) 加资产归因：BASE5 + 每种额外标的子集，同一窗口对比基线
    combos = [list(c) for r in range(1, 5) for c in itertools.combinations(EXTRAS, r)]
    rows = []
    for combo in combos:
        pool = BASE5 + combo
        W = build_window(data, pool)
        all_codes = sorted(set(BASE5) | set(combo))
        cl, op, vo, mo = precompute(data, all_codes, W)
        pool_grid = grid(pool, W, cl, op, vo, mo)
        base_onW = grid(BASE5, W, cl, op, vo, mo)
        pool_best = best_by_calmar(pool_grid)
        base_onW_best = best_by_calmar(base_onW)
        pool_fixed = pick(pool_grid, 2, 20, "biweekly")
        base_onW_fixed = pick(base_onW, 2, 20, "biweekly")
        rows.append({
            "combo": combo, "pool": pool, "window": [W[0], W[-1]], "n": len(W),
            "pool_fixed": pool_fixed, "base_fixed": base_onW_fixed,
            "pool_best": pool_best, "base_best": base_onW_best,
        })

    def line(tag, r):
        s = r["s"]
        return (f"  年化{s['ann']:+.2f}% 回撤-{s['mdd']:.2f}% 夏普{s['sharpe']:.2f} "
                f"卡玛{s['calmar']:.3f} 交易{s['trades']}")

    print("=" * 100)
    print("表A：固定官方参数(TOP2/双周/20日) —— 纯看『加资产』本身能否降回撤（同窗口 vs 基线）")
    print("=" * 100)
    print(f"{'新增标的':<26}{'窗口':<24}{'基线回撤':>10}{'新池回撤':>10}{'回撤变化':>10}"
          f"{'基线年化':>10}{'新池年化':>10}{'基线卡玛':>10}{'新池卡玛':>10}")
    for r in rows:
        bf, pf = r["base_fixed"]["s"], r["pool_fixed"]["s"]
        combo_name = "+".join(LABEL[c] for c in r["combo"])
        print(f"{combo_name:<26}{r['window'][0][:10]+'~':<24}{-bf['mdd']:>9.2f}%{-pf['mdd']:>9.2f}%"
              f"{(bf['mdd']-pf['mdd']):>+9.2f}%{bf['ann']:>9.2f}%{pf['ann']:>9.2f}%"
              f"{bf['calmar']:>10.3f}{pf['calmar']:>10.3f}")

    print("\n" + "=" * 100)
    print("表B：各池最优参数(TOP_K×动量×调仓 网格) —— 按卡玛排序，含相对同窗口基线的增量")
    print("=" * 100)
    ranked = sorted(rows, key=lambda r: r["pool_best"]["s"]["calmar"], reverse=True)
    print(f"{'排名':<4}{'新增标的':<24}{'窗口':<24}{'最优参数':<20}"
          f"{'年化':>8}{'回撤':>9}{'夏普':>7}{'卡玛':>8}{'Δ卡玛':>8}")
    for i, r in enumerate(ranked, 1):
        pb, bb = r["pool_best"], r["base_best"]
        s = pb["s"]
        params = f"TOP{pb['top_k']}/{pb['freq']}/{pb['md']}日"
        dcalmar = s["calmar"] - bb["s"]["calmar"]
        print(f"{i:<4}{('+'.join(LABEL[c] for c in r['combo'])):<24}"
              f"{r['window'][0][:10]+'~':<24}{params:<20}"
              f"{s['ann']:>8.2f}{-s['mdd']:>8.2f}%{s['sharpe']:>7.2f}{s['calmar']:>8.3f}{dcalmar:>+8.3f}")

    # 3) 结论
    print("\n" + "=" * 100)
    print("结论")
    print("=" * 100)
    fixed_improved = [r for r in rows if r["pool_fixed"]["s"]["mdd"] < r["base_fixed"]["s"]["mdd"]]
    best_improved_mdd = [r for r in rows if r["pool_best"]["s"]["mdd"] < r["base_best"]["s"]["mdd"]]
    print(f"固定参数下，回撤优于同窗口基线的组合数：{len(fixed_improved)}/{len(rows)}")
    for r in fixed_improved:
        print("  -", "+".join(LABEL[c] for c in r["combo"]),
              f"(基线-{r['base_fixed']['s']['mdd']:.2f}% → 新池-{r['pool_fixed']['s']['mdd']:.2f}%)")
    print(f"最优参数下，回撤优于同窗口基线的组合数：{len(best_improved_mdd)}/{len(rows)}")

    json.dump({
        "engine_check": chk,
        "baseline": {"fixed": base_fixed, "best": base_best},
        "additive": [{
            "combo": r["combo"], "pool": r["pool"], "window": r["window"],
            "pool_fixed": r["pool_fixed"], "base_fixed": r["base_fixed"],
            "pool_best": r["pool_best"], "base_best": r["base_best"],
        } for r in ranked],
    }, open(OUT, "w"), ensure_ascii=False, indent=2)
    print(f"\n结果已写入 {OUT}")


if __name__ == "__main__":
    main()
