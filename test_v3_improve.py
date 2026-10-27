#!/usr/bin/env python3
"""v3 进阶优化测试：国外大神方法落地验证
基线 v3：双周 · 20日动量 · TOP2 · 波动率目标15%(总波动率20日)
        年化21.20% ｜ 回撤-14.11% ｜ 夏普1.30 ｜ 卡玛1.503

测试改进项（每条独立叠加在v3上）：
  A) 多周期动量合成：20/60/120日 等权（vs 单一20日）
  B) 下行波动率目标：波动率目标只算下跌日（semivariance），替代总波动率
  C) 换手缓冲带：持仓跌出前2名不卖，跌出前3名才卖
  D) 绝对动量升级：动量信号与现金(0)比较已在v3；改测与"短债/货币"无关，测多周期版本
  E) 组合：多周期动量 + 下行波动率目标 + 缓冲带

成交：T日收盘算信号，T+1日开盘成交。
"""
import json, os, statistics
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "backtest_data", "prices_10y_open.json")
OUT = os.path.join(BASE, "backtest_data", "v3_improve_results.json")

ETFS = [("510300","沪深300"),("159915","创业板"),("513100","纳指"),("513500","标普500"),("518880","黄金")]
NAMES = [c for c,_ in ETFS]
CAPITAL = 3_000_000
COST = 0.0008
START = "2016-01-01"
ANNF = 244 ** 0.5
VOL_TARGET = 0.15
VOL_WIN = 20
TOP_K = 2
VOL_LIMIT = 0.02

data = json.load(open(DATA))
date_sets = [set(d for d,_ in data[n]) for n in NAMES]
DATES = sorted(set.intersection(*date_sets))
DATES = [d for d in DATES if d >= START]
CLOSE = {n:{d:v[1] for d,v in data[n]} for n in NAMES}
OPENP = {n:{d:v[0] for d,v in data[n]} for n in NAMES}
N = len(DATES)

def is_friday(d):
    return datetime.strptime(d, "%Y-%m-%d").weekday() == 4

def is_biweekly(i):
    d = DATES[i]
    return is_friday(d) and (i // 5) % 2 == 0

def total_vol(rets):
    m = sum(rets)/len(rets)
    return (sum((r-m)**2 for r in rets)/len(rets))**0.5

def downside_vol(rets):
    """下行波动率：只算负收益日的半方差"""
    neg = [r for r in rets if r < 0]
    if not neg:
        return 0.0
    return (sum(r**2 for r in neg)/len(rets))**0.5

def vol_scale(nav_arr, nav_now, use_downside=False):
    combined = nav_arr + [nav_now]
    if len(combined) >= VOL_WIN+1:
        rets = [combined[j]/combined[j-1]-1 for j in range(len(combined)-VOL_WIN, len(combined))]
        vol = downside_vol(rets) if use_downside else total_vol(rets)
        av = vol*ANNF
        return max(0.0, min(1.0, VOL_TARGET/av)) if av>0 else 1.0
    return 1.0

def momentum(i, n, windows):
    """多周期动量等权合成，返回均值"""
    moms = []
    for w in windows:
        if i >= w:
            moms.append(CLOSE[n][DATES[i]]/CLOSE[n][DATES[i-w]] - 1)
    return sum(moms)/len(moms) if moms else 0.0

def single_vol(i, n, win=20):
    rets = [CLOSE[n][DATES[j]]/CLOSE[n][DATES[j-1]]-1 for j in range(i-win+1, i+1)]
    return total_vol(rets)

def backtest(mom_windows=(20,), use_downside=False, buffer_k=0):
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

        if i >= max(mom_windows) and is_biweekly(i):
            # 算各标的多周期动量
            moms = {}
            for n in NAMES:
                moms[n] = momentum(i, n, mom_windows)
            ranked = sorted(NAMES, key=lambda n: moms[n], reverse=True)
            # 基线选股：只在动量前 TOP_K 名里看，波动被剔除就少买（不往后补位）
            target = [n for n in ranked[:TOP_K] if moms[n] > 0 and single_vol(i, n) <= VOL_LIMIT]
            # 缓冲带：若当前持仓标的已跌出前2名、但仍在"前 TOP_K+buffer_k 名"内，则继续保留
            if buffer_k > 0 and holdings:
                kept = [c for c in holdings if c not in target and c in ranked[:TOP_K + buffer_k]]
                if kept:
                    # 用保留的持仓替换掉 target 中排名更靠后的空位（target 可能不满 TOP_K）
                    target = (target + kept)[:TOP_K]
            nav_now = (cash + sum(h['shares']*CLOSE[c][d] for c,h in holdings.items()))/CAPITAL
            scale = vol_scale(nav_arr, nav_now, use_downside)
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
    print("v3 进阶优化测试（国外大神方法）\n")
    configs = [
        ("基线 v3（20日动量·总波动目标15%）", dict()),
        ("A: 多周期20/60/120等权", dict(mom_windows=(20,60,120))),
        ("A: 多周期20/60等权", dict(mom_windows=(20,60))),
        ("B: 下行波动率目标15%", dict(use_downside=True)),
        ("C: 缓冲带(跌出前3名才卖)", dict(buffer_k=1)),
        ("A+B: 多周期20/60/120 + 下行波动", dict(mom_windows=(20,60,120), use_downside=True)),
        ("A+B+C: 全组合", dict(mom_windows=(20,60,120), use_downside=True, buffer_k=1)),
    ]
    print(f"{'方案':<38}{'年化':>8}{'回撤':>8}{'夏普':>7}{'卡玛':>7}{'交易':>6}{'期末':>12}")
    print("-"*92)
    results = []
    for name, cfg in configs:
        r = backtest(**cfg)
        r['name'] = name
        results.append(r)
        print(f"{name:<38}{r['ann']:>7.2f}%{-r['mdd']:>7.2f}%{r['sharpe']:>7.2f}{r['calmar']:>7.3f}{r['trades']:>6d}{r['final']:>12,.0f}")

    results_sorted = sorted(results, key=lambda r: r['calmar'], reverse=True)
    print("\n按卡玛排序：")
    for r in results_sorted:
        print(f"  {r['name']:<38} 卡玛 {r['calmar']:.3f}")

    json.dump(results, open(OUT,'w'), ensure_ascii=False, indent=2)
    print(f"\n已保存 {OUT}")

if __name__ == "__main__":
    main()
