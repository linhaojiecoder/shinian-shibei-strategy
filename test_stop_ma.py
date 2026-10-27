#!/usr/bin/env python3
"""方向B测试：v3波动率目标基础上，加「单标的破N日线快速止损」
基线 v3：无止损 · 双周 · 20日动量 · TOP2 · 波动率目标15%·20日
       年化21.20% ｜ 回撤-14.11% ｜ 夏普1.30 ｜ 卡玛1.503

测试：持仓期间，若某标的收盘跌破自身 MA_N，则在次日开盘单独卖出该标的（空出仓位）
     N = 5 / 10 / 15 / 20
     卖出后是否立即换入新标的：两种模式
       a) 严格模式：卖出后不补，等下一个双周调仓日再重新选股
       b) 换入模式：卖出后用剩余资金按波动率目标系数买入当期动量第3名（若有）

成交：T日收盘算信号，T+1日开盘成交。
"""
import json, os, statistics
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "backtest_data", "prices_10y_open.json")
OUT = os.path.join(BASE, "backtest_data", "stop_ma_results.json")

ETFS = [("510300","沪深300"),("159915","创业板"),("513100","纳指"),("513500","标普500"),("518880","黄金")]
NAMES = [c for c,_ in ETFS]
LABEL = {c:n for c,n in ETFS}
CAPITAL = 3_000_000
MD = 20
VOL_N = 20
VOL_LIMIT = 0.02
TOP_K = 2
COST = 0.0008
START = "2016-01-01"
VOL_TARGET = 0.15
VOL_WIN = 20
ANNF = 244 ** 0.5

data = json.load(open(DATA))
date_sets = [set(d for d,_ in data[n]) for n in NAMES]
DATES = sorted(set.intersection(*date_sets))
DATES = [d for d in DATES if d >= START]
CLOSE = {n:{d:v[1] for d,v in data[n]} for n in NAMES}
OPENP = {n:{d:v[0] for d,v in data[n]} for n in NAMES}

def is_friday(d):
    return datetime.strptime(d, "%Y-%m-%d").weekday() == 4

def is_biweekly(i):
    d = DATES[i]
    return is_friday(d) and (i // 5) % 2 == 0

def ma_series(prices, w):
    out = [None]*len(prices)
    s = 0.0
    for i in range(len(prices)):
        s += prices[i]
        if i >= w:
            s -= prices[i-w]
        if i >= w-1:
            out[i] = s/w
    return out

# 预计算各标的各窗口均线
CMA = {n: {w: ma_series([CLOSE[n][d] for d in DATES], w) for w in (5,10,15,20)} for n in NAMES}

def momentum_target(i):
    metrics = {}
    for n in NAMES:
        mom = CLOSE[n][DATES[i]]/CLOSE[n][DATES[i-MD]] - 1
        rets = [CLOSE[n][DATES[j]]/CLOSE[n][DATES[j-1]]-1 for j in range(i-VOL_N+1, i+1)]
        m = sum(rets)/len(rets)
        vol = (sum((r-m)**2 for r in rets)/len(rets))**0.5
        metrics[n] = (mom, vol)
    ranked = sorted(NAMES, key=lambda n: metrics[n][0], reverse=True)
    target = [n for n in ranked[:TOP_K] if metrics[n][0] > 0 and metrics[n][1] <= VOL_LIMIT]
    return target, ranked, metrics

def vol_scale(nav_arr, nav_now):
    combined = nav_arr + [nav_now]
    if len(combined) >= VOL_WIN + 1:
        rets = [combined[j]/combined[j-1]-1 for j in range(len(combined)-VOL_WIN, len(combined))]
        m = sum(rets)/len(rets)
        vol = (sum((r-m)**2 for r in rets)/len(rets))**0.5
        ann_vol = vol*ANNF
        return max(0.0, min(1.0, VOL_TARGET/ann_vol)) if ann_vol > 0 else 1.0
    return 1.0

def backtest(ma_stop=None, refill=False):
    holdings = {}      # code -> {'shares':, 'cost':}
    cash = float(CAPITAL)
    nav_arr = []
    trades = 0
    pending_target = None
    pending_scale = 1.0
    pending_stop = set()   # 次日开盘卖出的标的

    for i, d in enumerate(DATES):
        # 1) 次日开盘执行止损卖出
        if i > 0:
            for c in list(pending_stop):
                if c in holdings:
                    h = holdings.pop(c)
                    p = OPENP[c][d]
                    cash += h['shares']*p*(1-COST)
                    trades += 1
            pending_stop = set()

        # 2) 次日开盘执行双周调仓
        if i > 0 and pending_target is not None:
            target, scale = pending_target, pending_scale
            total = cash + sum(h['shares']*OPENP[c][d] for c,h in holdings.items())
            n = len(target)
            each = total*scale/n if n > 0 else 0.0
            for c in list(holdings):
                if c not in target:
                    h = holdings.pop(c)
                    p = OPENP[c][d]
                    cash += h['shares']*p*(1-COST)
                    trades += 1
            for c in target:
                p = OPENP[c][d]
                cur_sh = holdings.get(c, {}).get('shares', 0)
                cur_v = cur_sh*p
                diff = each - cur_v
                if diff > p:
                    sh = int(diff/(p*(1+COST)))//100*100
                    if sh > 0:
                        old = holdings.get(c, {}).get('shares', 0)
                        old_cost = holdings.get(c, {}).get('cost', 0)
                        ts = old + sh
                        holdings[c] = {'shares': ts, 'cost': (old*old_cost+sh*p)/ts if ts>0 else p}
                        cash -= sh*p*(1+COST)
                        trades += 1
                elif diff < -p:
                    sh = min(cur_sh, int((-diff)/(p*(1-COST)))//100*100)
                    if sh > 0:
                        ns = cur_sh - sh
                        cash += sh*p*(1-COST)
                        trades += 1
                        if ns > 0: holdings[c]['shares'] = ns
                        else: holdings.pop(c, None)
            pending_target = None

        # 3) 收盘：双周调仓信号
        if i >= MD and is_biweekly(i):
            target, ranked, _ = momentum_target(i)
            nav_now = (cash + sum(h['shares']*CLOSE[c][d] for c,h in holdings.items()))/CAPITAL
            scale = vol_scale(nav_arr, nav_now)
            pending_target = (target,)
            pending_target = target
            pending_scale = scale
            # 换入模式：若有持仓被止损空出，且还有符合条件的第3名，双周时自然覆盖，不需额外处理

        # 4) 收盘：单标的破均线止损（每日检查）
        if ma_stop is not None and holdings:
            for c in list(holdings):
                ma_v = CMA[c][ma_stop][i]
                if ma_v is not None and CLOSE[c][d] < ma_v:
                    pending_stop.add(c)

        # 5) 记录净值
        mv = sum(h['shares']*CLOSE[c][d] for c,h in holdings.items())
        nav_arr.append((cash+mv)/CAPITAL)

    years = len(nav_arr)/244
    ann = ((nav_arr[-1]/nav_arr[0])**(1/years)-1)*100
    peak = nav_arr[0]; mdd = 0.0
    for v in nav_arr:
        peak = max(peak, v); mdd = max(mdd, (peak-v)/peak)
    rets = [nav_arr[j]/nav_arr[j-1]-1 for j in range(1, len(nav_arr))]
    sharpe = statistics.mean(rets)/statistics.pstdev(rets)*ANNF if statistics.pstdev(rets)>0 else 0
    calmar = ann/(mdd*100) if mdd>0 else 0
    return dict(ann=round(ann,2), mdd=round(mdd*100,2), sharpe=round(sharpe,2),
                calmar=round(calmar,3), trades=trades, final=round(nav_arr[-1]*CAPITAL,0))

def main():
    print("方向B：v3 + 单标的破N日线快速止损\n")
    configs = [("基线 v3（无单标的止损）", None)]
    for n in (5, 10, 15, 20):
        configs.append((f"单标的破MA{n}止损", n))

    print(f"{'方案':<24}{'年化':>8}{'回撤':>8}{'夏普':>7}{'卡玛':>7}{'交易':>6}{'期末':>12}")
    print("-"*80)
    results = []
    for name, cfg in configs:
        r = backtest(ma_stop=cfg)
        r['name'] = name
        results.append(r)
        print(f"{name:<24}{r['ann']:>7.2f}%{-r['mdd']:>7.2f}%{r['sharpe']:>7.2f}{r['calmar']:>7.3f}{r['trades']:>6d}{r['final']:>12,.0f}")

    results_sorted = sorted(results, key=lambda r: r['calmar'], reverse=True)
    print("\n按卡玛排序：")
    for r in results_sorted:
        print(f"  {r['name']:<24} 卡玛 {r['calmar']:.3f}")

    json.dump(results, open(OUT, 'w'), ensure_ascii=False, indent=2)
    print(f"\n已保存 {OUT}")

if __name__ == "__main__":
    main()
