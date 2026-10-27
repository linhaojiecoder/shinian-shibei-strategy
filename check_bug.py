import json, math

with open("backtest_data/prices.json") as f:
    data = json.load(f)
names = ["510300", "159915", "513100", "518880"]
date_sets = [set(d for d, _ in data[n]) for n in names]
common_dates = sorted(set.intersection(*date_sets))
prices = {n: {d: v for d, v in data[n]} for n in names}

# 复现 MA5 止损，逐日打印，看是否用了未来数据
def ma(dates, i, n, name):
    if i < n-1: return None
    return sum(prices[name][dates[j]] for j in range(i-n+1, i+1)) / n

# 关键问题：止损判断用的是当天收盘价 vs 当天MA，这没问题（都用当天数据）
# 但"跌破MA就平仓"，如果当天收盘已经跌破了，实际平仓价应该是当天收盘或次日开盘
# 我的实现里：先判断止损（用当天价），当天 ret 仍然用 hold 计算（即当天还在持仓）
# 这没问题。但让我检查 MA5 为什么这么神奇

# 打印 MA5 止损的持仓切换，看是否频繁进出导致"刚好躲过每次下跌"
hold=None; last=-10**9; navv=1.0
switches=0
hold_days={}
current_hold_start=None
for i in range(20, len(common_dates)):
    d=common_dates[i]
    moms={n: prices[n][d]/prices[n][common_dates[i-20]]-1 for n in names}
    if hold is not None:
        mav = ma(common_dates, i, 5, hold)
        if mav is not None and prices[hold][d] < mav:
            hold=None; last=i
            switches+=1
    if i-last>=5:
        last=i
        best=max(moms,key=moms.get)
        newhold = None if moms[best]<0 else best
        if newhold != hold:
            switches+=1
        hold=newhold

print(f"MA5止损方案：5年共 {switches} 次持仓切换")
print(f"平均每 {250*5/max(switches,1):.1f} 个交易日切换一次")

# 计算空仓天数占比
hold=None; last=-10**9; cash_days=0; total=0
for i in range(20, len(common_dates)):
    d=common_dates[i]
    moms={n: prices[n][d]/prices[n][common_dates[i-20]]-1 for n in names}
    if hold is not None:
        mav = ma(common_dates, i, 5, hold)
        if mav is not None and prices[hold][d] < mav:
            hold=None; last=i
    if i-last>=5:
        last=i
        best=max(moms,key=moms.get)
        hold=None if moms[best]<0 else best
    total+=1
    if hold is None: cash_days+=1
print(f"空仓天数占比：{cash_days/total*100:.1f}%")

# 关键验证：检查是否有"当天收盘跌破MA5，但当天ret却按持有算，次日又躲过下跌"的前视
# 实际上真正的bug可能是：止损后 last=i 让下一次调仓在 i+5 才发生，
# 但如果5天内又跌破MA5会再次空仓，这会导致"频繁空仓躲跌"
# 让我看看这个策略在2022年纳指大跌时的表现
hold=None; last=-10**9
print("\n2022年1-6月 MA5止损 持仓变化：")
for i in range(20, len(common_dates)):
    d=common_dates[i]
    if not (d>="2022-01-01" and d<="2022-06-30"): continue
    moms={n: prices[n][d]/prices[n][common_dates[i-20]]-1 for n in names}
    if hold is not None:
        mav = ma(common_dates, i, 5, hold)
        if mav is not None and prices[hold][d] < mav:
            hold=None; last=i
    if i-last>=5:
        last=i
        best=max(moms,key=moms.get)
        hold=None if moms[best]<0 else best
    h = "空仓" if hold is None else hold
    if i % 5 == 0 or hold is None:
        print(f"  {d} -> {h}")
