import json, math

with open("backtest_data/prices.json") as f:
    data = json.load(f)
names = ["510300", "159915", "513100", "518880"]
date_sets = [set(d for d, _ in data[n]) for n in names]
common_dates = sorted(set.intersection(*date_sets))
prices = {n: {d: v for d, v in data[n]} for n in names}
label = {"510300":"沪深300","159915":"创业板","513100":"纳指","518880":"黄金"}

# 最新交易日
last_date = common_dates[-1]
i = len(common_dates) - 1
print(f"最新交易日: {last_date}")
print(f"数据是否包含今天(2026-10-19): {'是' if last_date >= '2026-10-19' else '否，最新是 '+last_date}")
print()

# 计算动量(20日涨幅)
md = 20
print(f"【各标的 20日动量】")
moms = {}
for n in names:
    r = prices[n][last_date]/prices[n][common_dates[i-md]] - 1
    moms[n] = r
    print(f"  {label[n]}({n}): 今收 {prices[n][last_date]:.3f}  20日前 {prices[n][common_dates[i-md]]:.3f}  动量 {r*100:+.2f}%")

# 波动率(20日)
def vol(dates, i, n, name):
    if i < n: return None
    rets=[prices[name][dates[j]]/prices[name][dates[j-1]]-1 for j in range(i-n+1,i+1)]
    m=sum(rets)/len(rets)
    return (sum((r-m)**2 for r in rets)/len(rets))**0.5

print(f"\n【各标的 20日波动率】")
for n in names:
    v = vol(common_dates, i, 20, n)
    flag = "  <-- 超2%剔除" if v and v > 0.02 else ""
    print(f"  {label[n]}({n}): {v*100:.2f}%{flag}")

# 均线(20日)
def ma(dates, i, n, name):
    if i < n-1: return None
    return sum(prices[name][dates[j]] for j in range(i-n+1, i+1)) / n

print(f"\n【各标的 20日均线 vs 今收】")
for n in names:
    m = ma(common_dates, i, 20, n)
    p = prices[n][last_date]
    state = "站上均线" if p > m else "跌破均线"
    print(f"  {label[n]}({n}): 今收 {p:.3f}  MA20 {m:.3f}  {state}")

# 排名
ranked = sorted(moms, key=moms.get, reverse=True)
print(f"\n【动量排名】")
for r, n in enumerate(ranked, 1):
    print(f"  {r}. {label[n]}: {moms[n]*100:+.2f}%")

# 按策略规则选持仓
# 规则: 前3名 + 动量>0 + 波动率<2% + 价格在MA20上方
print(f"\n【策略信号判定】")
new_holds = []
for n in ranked[:3]:
    ok_mom = moms[n] > 0
    v = vol(common_dates, i, 20, n)
    ok_vol = v is not None and v <= 0.02
    m = ma(common_dates, i, 20, n)
    ok_ma = m is not None and prices[n][last_date] > m
    print(f"  {label[n]}: 动量{'+' if ok_mom else '-'} 波动率{'过' if not ok_vol else '合'} 均线{'站上' if ok_ma else '跌破'}")
    if ok_mom and ok_vol and ok_ma:
        new_holds.append(n)

print()
if new_holds:
    print(f"★ 当前应持有: {', '.join(label[n] for n in new_holds)}")
    print(f"  仓位: 各 1/{len(new_holds)} = {100/len(new_holds):.0f}%")
else:
    print(f"★ 当前应: 空仓（放货基）")
