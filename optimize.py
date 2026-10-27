import json, math

with open("backtest_data/prices.json") as f:
    data = json.load(f)
names = ["510300", "159915", "513100", "518880"]
date_sets = [set(d for d, _ in data[n]) for n in names]
common_dates = sorted(set.intersection(*date_sets))
prices = {n: {d: v for d, v in data[n]} for n in names}

def stats(nav):
    values = [v for _, v in nav]
    n = len(values)
    years = (n - 1) / 250.0
    ann_ret = (values[-1]) ** (1 / years) - 1 if years > 0 and values[-1] > 0 else 0
    peak = values[0]; max_dd = 0
    for v in values:
        if v > peak: peak = v
        dd = (v - peak) / peak
        if dd < max_dd: max_dd = dd
    daily = [values[i]/values[i-1]-1 for i in range(1,n)]
    mean_d = sum(daily)/len(daily)
    std_d = (sum((r-mean_d)**2 for r in daily)/len(daily))**0.5
    sharpe = mean_d/std_d*math.sqrt(250) if std_d>0 else 0
    return {"ann":ann_ret, "dd":max_dd, "sharpe":sharpe, "calmar":ann_ret/abs(max_dd) if max_dd else 0}

def ma(dates, i, n, name):
    """计算某 ETF 在 dates[i] 处的 n 日均线"""
    if i < n-1: return None
    s = sum(prices[name][dates[j]] for j in range(i-n+1, i+1))
    return s / n

def run_original(md=20, rb=5):
    nav=[]; hold=None; last=-10**9; navv=1.0
    for i in range(md, len(common_dates)):
        d=common_dates[i]
        moms={n: prices[n][d]/prices[n][common_dates[i-md]]-1 for n in names}
        if i-last>=rb:
            last=i
            best=max(moms,key=moms.get)
            hold=None if moms[best]<0 else best
        if i>0:
            pd=common_dates[i-1]
            ret = 0.0 if hold is None else prices[hold][d]/prices[hold][pd]-1
            navv*=(1+ret)
        nav.append((d,navv))
    return nav

# ===== 优化方案1：加均线过滤器（价格在MA上方才持有）=====
def run_ma_filter(md=20, rb=5, ma_days=20):
    nav=[]; hold=None; last=-10**9; navv=1.0
    for i in range(max(md,ma_days), len(common_dates)):
        d=common_dates[i]
        moms={n: prices[n][d]/prices[n][common_dates[i-md]]-1 for n in names}
        if i-last>=rb:
            last=i
            best=max(moms,key=moms.get)
            if moms[best]<0:
                hold=None
            else:
                # 检查best是否在MA上方
                ma_val = ma(common_dates, i, ma_days, best)
                hold = best if (ma_val is not None and prices[best][d] > ma_val) else None
        if i>0:
            pd=common_dates[i-1]
            ret = 0.0 if hold is None else prices[hold][d]/prices[hold][pd]-1
            navv*=(1+ret)
        nav.append((d,navv))
    return nav

# ===== 优化方案2：持仓期间跌破MA即止损（不止等调仓）=====
def run_ma_stop(md=20, rb=5, stop_ma=10):
    nav=[]; hold=None; last=-10**9; navv=1.0
    for i in range(max(md,stop_ma), len(common_dates)):
        d=common_dates[i]
        moms={n: prices[n][d]/prices[n][common_dates[i-md]]-1 for n in names}
        # 持仓止损：跌破短期MA即平仓
        if hold is not None:
            ma_val = ma(common_dates, i, stop_ma, hold)
            if ma_val is not None and prices[hold][d] < ma_val:
                hold=None; last=i
        if i-last>=rb:
            last=i
            best=max(moms,key=moms.get)
            hold=None if moms[best]<0 else best
        if i>0:
            pd=common_dates[i-1]
            ret = 0.0 if hold is None else prices[hold][d]/prices[hold][pd]-1
            navv*=(1+ret)
        nav.append((d,navv))
    return nav

# ===== 优化方案3：持仓回撤止损（从持仓高点回落X%即平）=====
def run_trailing_stop(md=20, rb=5, trail_pct=0.08):
    nav=[]; hold=None; last=-10**9; navv=1.0; hold_peak=None
    for i in range(md, len(common_dates)):
        d=common_dates[i]
        moms={n: prices[n][d]/prices[n][common_dates[i-md]]-1 for n in names}
        # 跟踪止损
        if hold is not None:
            p = prices[hold][d]
            if hold_peak is None or p > hold_peak:
                hold_peak = p
            if p < hold_peak * (1 - trail_pct):
                hold=None; last=i; hold_peak=None
        if i-last>=rb:
            last=i
            best=max(moms,key=moms.get)
            if moms[best]<0:
                hold=None; hold_peak=None
            else:
                if hold is None:  # 新开仓重置peak
                    hold_peak = prices[best][d]
                hold=best
        if i>0:
            pd=common_dates[i-1]
            ret = 0.0 if hold is None else prices[hold][d]/prices[hold][pd]-1
            navv*=(1+ret)
        nav.append((d,navv))
    return nav

# ===== 优化方案4：多持仓分散（持有动量前2名，各50%）=====
def run_top2(md=20, rb=5):
    nav=[]; holds=[]; last=-10**9; navv=1.0
    for i in range(md, len(common_dates)):
        d=common_dates[i]
        moms={n: prices[n][d]/prices[n][common_dates[i-md]]-1 for n in names}
        if i-last>=rb:
            last=i
            ranked = sorted(moms, key=moms.get, reverse=True)
            holds = [n for n in ranked[:2] if moms[n] > 0]
        if i>0:
            pd=common_dates[i-1]
            if not holds:
                ret=0.0
            else:
                ret = sum(prices[h][d]/prices[h][pd]-1 for h in holds)/len(holds)
            navv*=(1+ret)
        nav.append((d,navv))
    return nav

print("="*76)
print(f"{'方案':<26}{'年化':>8}{'回撤':>9}{'夏普':>8}{'Calmar':>9}")
print("-"*76)
orig = stats(run_original(20,5))
print(f"{'0. 原始(20日/周)':<26}{orig['ann']*100:>7.1f}%{orig['dd']*100:>8.1f}%{orig['sharpe']:>8.2f}{orig['calmar']:>9.2f}")

print("\n【方案1】均线过滤（价格需在MA上方才持有）")
for ma_d in [10,20,30,60]:
    s = stats(run_ma_filter(20,5,ma_d))
    print(f"{'  MA'+str(ma_d)+'过滤':<26}{s['ann']*100:>7.1f}%{s['dd']*100:>8.1f}%{s['sharpe']:>8.2f}{s['calmar']:>9.2f}")

print("\n【方案2】持仓跌破短期MA即止损")
for sm in [5,10,15,20]:
    s = stats(run_ma_stop(20,5,sm))
    print(f"{'  止损MA'+str(sm):<26}{s['ann']*100:>7.1f}%{s['dd']*100:>8.1f}%{s['sharpe']:>8.2f}{s['calmar']:>9.2f}")

print("\n【方案3】跟踪止损（从持仓高点回落X%平仓）")
for tp in [0.05,0.08,0.10,0.15]:
    s = stats(run_trailing_stop(20,5,tp))
    print(f"{'  回落'+str(int(tp*100))+'%止损':<26}{s['ann']*100:>7.1f}%{s['dd']*100:>8.1f}%{s['sharpe']:>8.2f}{s['calmar']:>9.2f}")

print("\n【方案4】持有动量前2名（各50%分散）")
s = stats(run_top2(20,5))
print(f"{'  前2名等权':<26}{s['ann']*100:>7.1f}%{s['dd']*100:>8.1f}%{s['sharpe']:>8.2f}{s['calmar']:>9.2f}")
