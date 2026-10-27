#!/usr/bin/env python3
"""金叉死叉策略测试：MA5/MA10 金叉买、死叉卖
对比基线 v3（双周·20日动量·TOP2·波动率目标15%）

规则变体：
  A) 纯金叉死叉轮动：任一标的金叉则买入(等权TOP1/2)，死叉则卖出，空仓等下一个金叉
  B) 金叉死叉 + 波动率目标15%
  交叉参数：MA5/10、MA10/20、MA20/60

成交：T日收盘算信号，T+1日开盘成交，消除前视偏差。
"""
import json, os, statistics
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "backtest_data", "prices_10y_open.json")
OUT = os.path.join(BASE, "backtest_data", "cross_results.json")

ETFS = [("510300","沪深300"),("159915","创业板"),("513100","纳指"),("513500","标普500"),("518880","黄金")]
NAMES = [c for c,_ in ETFS]
LABEL = {c:n for c,n in ETFS}
CAPITAL = 3_000_000
COST = 0.0008
START = "2016-01-01"
ANNF = 244 ** 0.5
VOL_TARGET = 0.15
VOL_WIN = 20

data = json.load(open(DATA))
date_sets = [set(d for d,_ in data[n]) for n in NAMES]
DATES = sorted(set.intersection(*date_sets))
DATES = [d for d in DATES if d >= START]
CLOSE = {n:{d:v[1] for d,v in data[n]} for n in NAMES}
OPENP = {n:{d:v[0] for d,v in data[n]} for n in NAMES}

def ma(arr, w):
    out = [None]*len(arr)
    s = 0.0
    for i in range(len(arr)):
        s += arr[i]
        if i >= w: s -= arr[i-w]
        if i >= w-1: out[i] = s/w
    return out

# 预计算各标的各窗口均线
PRICE = {n: [CLOSE[n][d] for d in DATES] for n in NAMES}
MA = {n: {w: ma(PRICE[n], w) for w in (5,10,20,60)} for n in NAMES}

def vol_scale(nav_arr, nav_now):
    combined = nav_arr + [nav_now]
    if len(combined) >= VOL_WIN+1:
        rets = [combined[j]/combined[j-1]-1 for j in range(len(combined)-VOL_WIN, len(combined))]
        m = sum(rets)/len(rets)
        vol = (sum((r-m)**2 for r in rets)/len(rets))**0.5
        av = vol*ANNF
        return max(0.0, min(1.0, VOL_TARGET/av)) if av>0 else 1.0
    return 1.0

def backtest(fast, slow, top_k=1, use_voltarget=False):
    holdings = {}
    cash = float(CAPITAL)
    nav_arr = []
    trades = 0
    pending_target = None
    pending_scale = 1.0

    for i, d in enumerate(DATES):
        # 1) 次日开盘执行
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

        # 2) 收盘算金叉死叉信号
        if i >= slow:
            # 找出金叉（MA_fast 上穿 MA_slow）的标的
            golden = []
            for n in NAMES:
                f_now = MA[n][fast][i]; s_now = MA[n][slow][i]
                f_prev = MA[n][fast][i-1]; s_prev = MA[n][slow][i-1]
                if None in (f_now, s_now, f_prev, s_prev):
                    continue
                if f_prev <= s_prev and f_now > s_now:
                    golden.append(n)
            # 目标 = 金叉标的（等权取 top_k 个，按当前价格动量排序）
            if golden:
                ranked = sorted(golden, key=lambda n: PRICE[n][i]/PRICE[n][max(0,i-20)]-1, reverse=True)
                target = ranked[:top_k]
            else:
                target = []
            # 死叉的标的从持仓剔除（已含在 target 判定中，target 为空则清仓）
            nav_now = (cash + sum(h['shares']*CLOSE[c][d] for c,h in holdings.items()))/CAPITAL
            scale = vol_scale(nav_arr, nav_now) if use_voltarget else 1.0
            # 若当前持仓标的出现死叉，从 target 剔除
            for c in list(holdings):
                f_now = MA[c][fast][i]; s_now = MA[c][slow][i]
                f_prev = MA[c][fast][i-1]; s_prev = MA[c][slow][i-1]
                if None in (f_now,s_now,f_prev,s_prev):
                    continue
                if f_prev >= s_prev and f_now < s_now:  # 死叉
                    if c in target:
                        target.remove(c)
            pending_target = target
            pending_scale = scale

        # 3) 记录净值
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
    print("金叉死叉策略测试\n")
    configs = [
        ("基线 v3（双周·20日动量·TOP2·波动目标15%）", None),
        ("MA5/10 金叉买死叉卖 TOP1", (5,10,1,False)),
        ("MA5/10 金叉买死叉卖 TOP2", (5,10,2,False)),
        ("MA10/20 金叉买死叉卖 TOP1", (10,20,1,False)),
        ("MA10/20 金叉买死叉卖 TOP2", (10,20,2,False)),
        ("MA20/60 金叉买死叉卖 TOP1", (20,60,1,False)),
        ("MA5/10 金叉死叉 + 波动目标15%", (5,10,1,True)),
        ("MA10/20 金叉死叉 + 波动目标15%", (10,20,2,True)),
    ]
    print(f"{'方案':<38}{'年化':>8}{'回撤':>8}{'夏普':>7}{'卡玛':>7}{'交易':>6}{'期末':>12}")
    print("-"*92)
    results = []
    for name, cfg in configs:
        if cfg is None:
            # 直接用已知基线
            r = dict(ann=21.20, mdd=14.11, sharpe=1.30, calmar=1.503, trades=569, final=23642675)
        else:
            f,s,k,vt = cfg
            r = backtest(f,s,k,vt)
        r['name'] = name
        results.append(r)
        print(f"{name:<38}{r['ann']:>7.2f}%{-r['mdd']:>7.2f}%{r['sharpe']:>7.2f}{r['calmar']:>7.3f}{r['trades']:>6d}{r['final']:>12,.0f}")

    json.dump(results, open(OUT,'w'), ensure_ascii=False, indent=2)
    print(f"\n已保存 {OUT}")

if __name__ == "__main__":
    main()
