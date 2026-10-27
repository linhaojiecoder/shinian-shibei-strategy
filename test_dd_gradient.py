#!/usr/bin/env python3
"""v3 回撤梯度加减仓测试：回撤越深越加仓、涨回越减仓
基线 v3：双周 · 20日动量 · TOP2 · 波动率目标15%·20日
        年化21.20% ｜ 回撤-14.11% ｜ 夏普1.30 ｜ 卡玛1.503

机制：在波动率目标 scale 基础上，再乘一个「回撤系数 dd_scale」：
  回撤越深 → dd_scale 越大（越跌越买，抄底）
  回撤越浅/创新高 → dd_scale 越小（越涨越卖，落袋）

测试几种梯度设计：
  G1 线性：dd_scale = 1 + dd / 0.20   （回撤20%时加满到2倍，但cap在1.2）
  G2 阶梯：dd<5%→0.9, 5~10%→1.0, 10~15%→1.1, >15%→1.2
  G3 逆向：回撤越大仓位越高，上限1.5倍
  以及「跌加仓但顶部减仓」的对称版本

成交：T日收盘算信号，T+1日开盘成交。
"""
import json, os, statistics
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "backtest_data", "prices_10y_open.json")
OUT = os.path.join(BASE, "backtest_data", "dd_gradient_results.json")

ETFS = [("510300","沪深300"),("159915","创业板"),("513100","纳指"),("513500","标普500"),("518880","黄金")]
NAMES = [c for c,_ in ETFS]
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

def vol_scale(nav_arr, nav_now):
    combined = nav_arr + [nav_now]
    if len(combined) >= VOL_WIN+1:
        rets = [combined[j]/combined[j-1]-1 for j in range(len(combined)-VOL_WIN, len(combined))]
        m = sum(rets)/len(rets)
        vol = (sum((r-m)**2 for r in rets)/len(rets))**0.5
        av = vol*ANNF
        return max(0.0, min(1.0, VOL_TARGET/av)) if av>0 else 1.0
    return 1.0

def dd_scale_fn(mode, dd):
    """dd 为回撤幅度（0~1，正数）。返回回撤系数。"""
    if mode == 'none':
        return 1.0
    if mode == 'linear':
        # 回撤越深仓位越高：dd=0→0.9, dd=0.2→1.1
        return 0.9 + dd * 1.0
    if mode == 'step':
        # 阶梯
        if dd < 0.05: return 0.9
        elif dd < 0.10: return 1.0
        elif dd < 0.15: return 1.1
        else: return 1.2
    if mode == 'aggressive':
        # 激进逆向：dd=0→0.8, dd=0.2→1.5
        return 0.8 + dd * 3.5
    return 1.0

def backtest(dd_mode='none', cap=1.2):
    holdings = {}
    cash = float(CAPITAL)
    nav_arr = []
    trades = 0
    pending_target = None
    pending_scale = 1.0

    for i, d in enumerate(DATES):
        if i > 0 and pending_target is not None:
            target, scale = pending_target, pending_scale
            total = cash + sum(h['shares']*OPENP[c][d] for c,h in holdings.items())
            n = len(target)
            each = total*scale/n if n>0 else 0.0
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
                    if sh>0:
                        old = holdings.get(c,{}).get('shares',0)
                        old_cost = holdings.get(c,{}).get('cost',0)
                        ts = old+sh
                        holdings[c] = {'shares':ts,'cost':(old*old_cost+sh*p)/ts if ts>0 else p}
                        cash -= sh*p*(1+COST)
                        trades += 1
                elif diff < -p:
                    sh = min(cur_sh, int((-diff)/(p*(1-COST)))//100*100)
                    if sh>0:
                        ns = cur_sh-sh
                        cash += sh*p*(1-COST)
                        trades += 1
                        if ns>0: holdings[c]['shares']=ns
                        else: holdings.pop(c,None)
            pending_target = None

        if i >= MD and is_biweekly(i):
            metrics = {}
            for n in NAMES:
                mom = CLOSE[n][d]/CLOSE[n][DATES[i-MD]] - 1
                rets = [CLOSE[n][DATES[j]]/CLOSE[n][DATES[j-1]]-1 for j in range(i-VOL_N+1, i+1)]
                m = sum(rets)/len(rets)
                vol = (sum((r-m)**2 for r in rets)/len(rets))**0.5
                metrics[n] = (mom, vol)
            ranked = sorted(NAMES, key=lambda n: metrics[n][0], reverse=True)
            target = [n for n in ranked[:TOP_K] if metrics[n][0] > 0 and metrics[n][1] <= VOL_LIMIT]

            nav_now = (cash + sum(h['shares']*CLOSE[c][d] for c,h in holdings.items()))/CAPITAL
            combined = nav_arr + [nav_now]
            peak = max(combined) if combined else nav_now
            dd = (peak - nav_now)/peak if peak > 0 else 0.0

            vs = vol_scale(nav_arr, nav_now)
            ds = dd_scale_fn(dd_mode, dd)
            scale = min(cap, vs * ds)
            pending_target = target
            pending_scale = scale

        mv = sum(h['shares']*CLOSE[c][d] for c,h in holdings.items())
        nav_arr.append((cash+mv)/CAPITAL)

    years = len(nav_arr)/244
    ann = ((nav_arr[-1]/nav_arr[0])**(1/years)-1)*100
    peak = nav_arr[0]; mdd = 0.0
    for v in nav_arr:
        peak = max(peak,v); mdd = max(mdd,(peak-v)/peak)
    rets = [nav_arr[j]/nav_arr[j-1]-1 for j in range(1,len(nav_arr))]
    sharpe = statistics.mean(rets)/statistics.pstdev(rets)*ANNF if statistics.pstdev(rets)>0 else 0
    calmar = ann/(mdd*100) if mdd>0 else 0
    return dict(ann=round(ann,2), mdd=round(mdd*100,2), sharpe=round(sharpe,2),
                calmar=round(calmar,3), trades=trades, final=round(nav_arr[-1]*CAPITAL,0))

def main():
    print("v3 回撤梯度加减仓测试\n")
    configs = [
        ("基线 v3（无回撤梯度）", 'none', 1.0),
        ("G1 线性：0.9+dd", 'linear', 1.2),
        ("G2 阶梯：0.9/1.0/1.1/1.2", 'step', 1.2),
        ("G3 激进逆向：0.8+3.5dd", 'aggressive', 1.5),
        ("G1 线性 cap1.5", 'linear', 1.5),
        ("G2 阶梯 cap1.5", 'step', 1.5),
    ]
    print(f"{'方案':<34}{'年化':>8}{'回撤':>8}{'夏普':>7}{'卡玛':>7}{'交易':>6}{'期末':>12}")
    print("-"*86)
    results = []
    for name, mode, cap in configs:
        r = backtest(mode, cap)
        r['name'] = name
        results.append(r)
        print(f"{name:<34}{r['ann']:>7.2f}%{-r['mdd']:>7.2f}%{r['sharpe']:>7.2f}{r['calmar']:>7.3f}{r['trades']:>6d}{r['final']:>12,.0f}")

    results_sorted = sorted(results, key=lambda r: r['calmar'], reverse=True)
    print("\n按卡玛排序：")
    for r in results_sorted:
        print(f"  {r['name']:<34} 卡玛 {r['calmar']:.3f}")

    json.dump(results, open(OUT,'w'), ensure_ascii=False, indent=2)
    print(f"\n已保存 {OUT}")

if __name__ == "__main__":
    main()
