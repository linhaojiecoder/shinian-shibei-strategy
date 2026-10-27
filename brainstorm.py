import json, math

with open("backtest_data/prices.json") as f:
    data = json.load(f)
names = ["510300", "159915", "513100", "518880"]
date_sets = [set(d for d, _ in data[n]) for n in names]
common_dates = sorted(set.intersection(*date_sets))
prices = {n: {d: v for d, v in data[n]} for n in names}
label = {"510300":"沪深300","159915":"创业板","513100":"纳指","518880":"黄金"}

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
    if i < n-1: return None
    return sum(prices[name][dates[j]] for j in range(i-n+1, i+1)) / n

def vol(dates, i, n, name):
    """n日波动率（日收益率标准差）"""
    if i < n: return None
    rets = [prices[name][dates[j]]/prices[name][dates[j-1]]-1 for j in range(i-n+1, i+1)]
    m = sum(rets)/len(rets)
    return (sum((r-m)**2 for r in rets)/len(rets))**0.5

def run_engine(md=20, rb=5, topk=3, cost=0.0008, ma_stop=0, 
               vol_filter=None, vol_stop=None, use_rsi=False, rsi_buy=None, rsi_sell=None,
               hold_threshold=0.0, momentum_type="simple", lookback_vol=20):
    """超通用回测引擎"""
    nav=[]; holds=[]; last=-10**9; navv=1.0; switches=0
    for i in range(max(md, ma_stop, 30), len(common_dates)):
        d=common_dates[i]
        # 动量计算
        if momentum_type == "simple":
            moms={n: prices[n][d]/prices[n][common_dates[i-md]]-1 for n in names}
        elif momentum_type == "risk_adj":  # 风险调整动量 = 收益/波动率
            moms={}
            for n in names:
                v = vol(common_dates, i, lookback_vol, n)
                r = prices[n][d]/prices[n][common_dates[i-md]]-1
                moms[n] = r/(v if v and v>0 else 0.01)

        # 持仓止损：跌破MA清仓
        if ma_stop > 0 and holds:
            new_holds = []
            for h in holds:
                mav = ma(common_dates, i, ma_stop, h)
                if mav is None or prices[h][d] > mav:
                    new_holds.append(h)
            if set(new_holds) != set(holds):
                turnover = len(new_holds) + len(holds)
                navv *= (1 - cost * turnover / 2); switches += 1
            holds = new_holds

        # 波动率止损：持仓标的波动率过高则清仓
        if vol_stop is not None and holds:
            new_holds = []
            for h in holds:
                v = vol(common_dates, i, lookback_vol, h)
                if v is None or v < vol_stop:
                    new_holds.append(h)
            if set(new_holds) != set(holds):
                turnover = len(new_holds) + len(holds)
                navv *= (1 - cost * turnover / 2); switches += 1
            holds = new_holds

        # 调仓
        if i-last>=rb:
            last=i
            ranked = sorted(moms, key=moms.get, reverse=True)
            new_holds = []
            for n in ranked[:topk]:
                if moms[n] <= hold_threshold: continue
                # 波动率过滤：开仓时波动率不能过高
                if vol_filter is not None:
                    v = vol(common_dates, i, lookback_vol, n)
                    if v is not None and v > vol_filter:
                        continue
                new_holds.append(n)
            if set(new_holds) != set(holds):
                turnover = len(new_holds) + len(holds)
                navv *= (1 - cost * turnover / 2); switches += 1
            holds = new_holds

        if i>0:
            pd=common_dates[i-1]
            ret = 0.0 if not holds else sum(prices[h][d]/prices[h][pd]-1 for h in holds)/len(holds)
            navv*=(1+ret)
        nav.append((d,navv))
    return nav, switches

print("="*84)
print("深度发散回测（前3名基准：年化25.6% 回撤-14.7% 夏普1.35）")
print("="*84)
print(f"{'思路':<34}{'年化':>8}{'回撤':>9}{'夏普':>8}{'Calmar':>9}{'切换':>6}")
print("-"*84)

# 基准
nav,sw = run_engine(20,5,3,0.0008)
s=stats(nav)
print(f"{'0. 基准（前3名）':<34}{s['ann']*100:>7.1f}%{s['dd']*100:>8.1f}%{s['sharpe']:>8.2f}{s['calmar']:>9.2f}{sw:>6}")

print("\n【思路1】风险调整动量（收益/波动率，选更稳的标的）")
for lb in [10,20,40]:
    nav,sw = run_engine(20,5,3,0.0008, momentum_type="risk_adj", lookback_vol=lb)
    s=stats(nav)
    print(f"{'  风险调整动量(波动'+str(lb)+'日)':<32}{s['ann']*100:>7.1f}%{s['dd']*100:>8.1f}%{s['sharpe']:>8.2f}{s['calmar']:>9.2f}{sw:>6}")

print("\n【思路2】波动率过滤（高波动标的剔除）")
for vf in [0.01, 0.015, 0.02]:
    nav,sw = run_engine(20,5,3,0.0008, vol_filter=vf, lookback_vol=20)
    s=stats(nav)
    print(f"{'  波动率>'+str(int(vf*100))+'%剔除':<32}{s['ann']*100:>7.1f}%{s['dd']*100:>8.1f}%{s['sharpe']:>8.2f}{s['calmar']:>9.2f}{sw:>6}")

print("\n【思路3】持仓波动率止损（持仓变高波动就撤）")
for vs in [0.02, 0.025, 0.03]:
    nav,sw = run_engine(20,5,3,0.0008, vol_stop=vs, lookback_vol=20)
    s=stats(nav)
    print(f"{'  波动率>'+str(int(vs*100))+'%止损':<32}{s['ann']*100:>7.1f}%{s['dd']*100:>8.1f}%{s['sharpe']:>8.2f}{s['calmar']:>9.2f}{sw:>6}")

print("\n【思路4】提升买入门槛（动量需>X%才持有）")
for th in [0.0, 0.02, 0.05, 0.08]:
    nav,sw = run_engine(20,5,3,0.0008, hold_threshold=th)
    s=stats(nav)
    print(f"{'  动量>'+str(int(th*100))+'%才持有':<32}{s['ann']*100:>7.1f}%{s['dd']*100:>8.1f}%{s['sharpe']:>8.2f}{s['calmar']:>9.2f}{sw:>6}")

print("\n【思路5】组合：跌破MA20清仓 + 风险调整动量")
for md in [20,40]:
    nav,sw = run_engine(md,5,3,0.0008, ma_stop=20, momentum_type="risk_adj", lookback_vol=20)
    s=stats(nav)
    print(f"{'  风险动量+MA20止损(md'+str(md)+')':<30}{s['ann']*100:>7.1f}%{s['dd']*100:>8.1f}%{s['sharpe']:>8.2f}{s['calmar']:>9.2f}{sw:>6}")

print("\n【思路6】组合：跌破MA20清仓 + 波动率过滤")
for vf in [0.015, 0.02]:
    nav,sw = run_engine(20,5,3,0.0008, ma_stop=20, vol_filter=vf, lookback_vol=20)
    s=stats(nav)
    print(f"{'  MA20止损+波动>'+str(int(vf*100))+'%剔除':<30}{s['ann']*100:>7.1f}%{s['dd']*100:>8.1f}%{s['sharpe']:>8.2f}{s['calmar']:>9.2f}{sw:>6}")
