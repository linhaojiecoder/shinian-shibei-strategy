#!/usr/bin/env python3
"""十年十倍目标 · 参数网格扫描
目标：年化接近或超过 25.9%（十年十倍），同时控制回撤。
扫描维度：
  - 止损均线 MA: 20 / 40 / 60 / 120 / 无止损
  - 调仓频率: 每周 / 每两周 / 每月
  - 动量窗口 MD: 20 / 60 / 120
  - 持仓数 TOP_K: 1 / 2 / 3
  - 波动率过滤: 开 / 关
所有组合都用次日开盘成交（无前视偏差），统计年化/回撤/夏普/交易次数。
"""
import json, os
from datetime import datetime
import statistics
from itertools import product

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "backtest_data", "prices_10y_open.json")

ETFS = [("510300","沪深300"),("159915","创业板"),("513100","纳指"),("513500","标普500"),("518880","黄金")]
NAMES = [c for c,_ in ETFS]
LABEL = {c:n for c,n in ETFS}

CAPITAL = 3_000_000
COST = 0.0008
START = "2016-01-01"

data = json.load(open(DATA))
date_sets = [set(d for d,_ in data[n]) for n in NAMES]
DATES = sorted(set.intersection(*date_sets))
DATES = [d for d in DATES if d >= START]
CLOSE = {n:{d:v[1] for d,v in data[n]} for n in NAMES}
OPENP = {n:{d:v[0] for d,v in data[n]} for n in NAMES}

def is_friday(d):
    return datetime.strptime(d, "%Y-%m-%d").weekday() == 4

def rebalance_day(i, freq):
    """判断第 i 个交易日是否调仓日"""
    d = DATES[i]
    if freq == 'weekly':
        return is_friday(d)
    elif freq == 'biweekly':
        # 每两周的周五
        return is_friday(d) and (i // 5) % 2 == 0
    elif freq == 'monthly':
        # 每月第一个交易日（或每月最后一天）
        return d[5:7] != DATES[i-1][5:7] if i > 0 else False
    return False

def backtest(ma_n, freq, md, top_k, vol_on):
    holdings = {}
    cash = CAPITAL
    nav_series = []
    trade_count = 0
    pending_target = None
    pending_stop = set()

    for i, d in enumerate(DATES):
        # 执行 pending
        if i > 0 and (pending_target is not None or pending_stop):
            for code in list(pending_stop):
                if code in holdings:
                    h = holdings.pop(code)
                    p = OPENP[code][d]
                    cash += h["shares"] * p * (1 - COST)
                    trade_count += 1
            if pending_target is not None:
                for code in list(holdings.keys()):
                    if code not in pending_target and code not in pending_stop:
                        h = holdings.pop(code)
                        p = OPENP[code][d]
                        cash += h["shares"]*p*(1-COST)
                        trade_count += 1
                if pending_target:
                    mv = sum(holdings[c]["shares"]*OPENP[c][d] for c in holdings)
                    total = cash + mv
                    each = total / len(pending_target)
                    for code in pending_target:
                        p = OPENP[code][d]
                        cur_sh = holdings.get(code, {}).get("shares", 0)
                        diff = each - cur_sh * p
                        if diff > p:
                            sh = int(diff / (p*(1+COST))) // 100 * 100
                            if sh > 0:
                                old_sh = holdings.get(code, {}).get("shares",0)
                                holdings[code] = {"shares": old_sh + sh}
                                cash -= sh*p*(1+COST)
                                trade_count += 1
            pending_target = None
            pending_stop = set()

        # 止损信号（ma_n=0 表示不止损）
        if ma_n > 0 and i >= ma_n:
            for code in list(holdings.keys()):
                ma = sum(CLOSE[code][DATES[j]] for j in range(i-ma_n+1, i+1)) / ma_n
                if CLOSE[code][d] < ma:
                    pending_stop.add(code)

        # 调仓信号
        if rebalance_day(i, freq) and i >= md:
            metrics = {}
            for n in NAMES:
                mom = CLOSE[n][d] / CLOSE[n][DATES[i-md]] - 1
                ma = sum(CLOSE[n][DATES[j]] for j in range(i-ma_n+1,i+1)) / ma_n if ma_n>0 else 0
                rets = [CLOSE[n][DATES[j]]/CLOSE[n][DATES[j-1]]-1 for j in range(i-20+1,i+1)]
                m = sum(rets)/len(rets)
                vol = (sum((r-m)**2 for r in rets)/len(rets))**0.5
                above = CLOSE[n][d] > ma if ma_n>0 else True
                metrics[n] = {"mom":mom, "above":above, "vol":vol}
            ranked = sorted(NAMES, key=lambda n: metrics[n]["mom"], reverse=True)
            target = []
            for n in ranked[:top_k]:
                if metrics[n]["mom"]>0 and metrics[n]["above"]:
                    if vol_on and metrics[n]["vol"] > 0.02:
                        continue
                    target.append(n)
            pending_target = target

        mv = sum(holdings[c]["shares"]*CLOSE[c][d] for c in holdings)
        total = cash + mv
        nav_series.append(total / CAPITAL)

    navs = nav_series
    total_ret = (navs[-1]/navs[0]-1)*100
    years = len(navs)/244
    ann = ((navs[-1]/navs[0])**(1/years)-1)*100
    peak = navs[0]; mdd = 0
    for v in navs:
        peak = max(peak, v); mdd = max(mdd, (peak-v)/peak)
    rets = [navs[i]/navs[i-1]-1 for i in range(1,len(navs))]
    sharpe = statistics.mean(rets)/statistics.pstdev(rets)*(244**0.5) if statistics.pstdev(rets)>0 else 0
    # 卡玛比率 = 年化/回撤
    calmar = ann/(mdd*100) if mdd > 0 else 0
    return {"ann": ann, "mdd": mdd*100, "sharpe": sharpe, "trades": trade_count,
            "total_ret": total_ret, "calmar": calmar}

if __name__ == "__main__":
    results = []
    ma_opts = [20, 40, 60, 120, 0]
    freq_opts = ['weekly', 'biweekly', 'monthly']
    md_opts = [20, 60, 120]
    topk_opts = [1, 2, 3]
    vol_opts = [True, False]

    total_combos = len(ma_opts)*len(freq_opts)*len(md_opts)*len(topk_opts)*len(vol_opts)
    print(f"共 {total_combos} 组参数组合，开始扫描...")

    for ma_n, freq, md, top_k, vol_on in product(ma_opts, freq_opts, md_opts, topk_opts, vol_opts):
        r = backtest(ma_n, freq, md, top_k, vol_on)
        r.update({"ma_n": ma_n, "freq": freq, "md": md, "top_k": top_k, "vol_on": vol_on})
        results.append(r)

    # 排序：优先年化，但也要看回撤和夏普
    results.sort(key=lambda x: x["ann"], reverse=True)

    print("\n=== 年化收益 TOP 20 ===")
    print(f"{'排名':<4}{'年化':>8}{'回撤':>8}{'夏普':>7}{'卡玛':>7}{'交易':>6}  MA  频率   动量  持仓  波动过滤")
    for i, r in enumerate(results[:20]):
        print(f"{i+1:<4}{r['ann']:>7.2f}%{r['mdd']:>7.2f}%{r['sharpe']:>6.2f}{r['calmar']:>6.2f}{r['trades']:>6}  "
              f"MA{r['ma_n']}  {r['freq']:<9}{r['md']:<5}  {r['top_k']}只  {'开' if r['vol_on'] else '关'}")

    # 按夏普排序
    results.sort(key=lambda x: x["sharpe"], reverse=True)
    print("\n=== 夏普比率 TOP 10 ===")
    for i, r in enumerate(results[:10]):
        print(f"{i+1}. 夏普{r['sharpe']:.2f} 年化{r['ann']:.2f}% 回撤{r['mdd']:.2f}% 卡玛{r['calmar']:.2f}  "
              f"MA{r['ma_n']} {r['freq']} MD{r['md']} TOP{r['top_k']} 波动{'开' if r['vol_on'] else '关'}")

    # 按卡玛排序
    results.sort(key=lambda x: x["calmar"], reverse=True)
    print("\n=== 卡玛比率(年化/回撤) TOP 10 ===")
    for i, r in enumerate(results[:10]):
        print(f"{i+1}. 卡玛{r['calmar']:.2f} 年化{r['ann']:.2f}% 回撤{r['mdd']:.2f}% 夏普{r['sharpe']:.2f}  "
              f"MA{r['ma_n']} {r['freq']} MD{r['md']} TOP{r['top_k']} 波动{'开' if r['vol_on'] else '关'}")

    json.dump(results, open("backtest_data/scan_results.json","w"), ensure_ascii=False)
    print("\n✅ 已保存 backtest_data/scan_results.json")
