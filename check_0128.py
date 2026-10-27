import json

with open("backtest_data/prices.json") as f:
    data = json.load(f)

px = {d:v for d,v in data["518880"]}
print("黄金ETF 1月下旬逐日：")
for d in sorted(px):
    if "2026-01-20" <= d <= "2026-02-03":
        print(f"  {d}  收 {px[d]:.3f}")

# 计算每天涨跌幅
print("\n逐日涨跌幅：")
keys = sorted(px.keys())
idx = {d:i for i,d in enumerate(keys)}
for d in sorted(px):
    if "2026-01-26" <= d <= "2026-02-03":
        i = idx[d]
        if i>0:
            prev = keys[i-1]
            print(f"  {d}: {(px[d]/px[prev]-1)*100:+.2f}%")

# 20日均线在1/28的值
print("\n黄金 20日均线(MA20) 关键日：")
vals = sorted(px.items())
for target in ["2026-01-28","2026-01-29","2026-01-30","2026-02-02"]:
    ti = next(i for i,(d,v) in enumerate(vals) if d==target)
    if ti >= 19:
        ma20 = sum(v for d,v in vals[ti-19:ti+1])/20
        print(f"  {target}: 收盘 {px[target]:.3f}  MA20 {ma20:.3f}  {'站上' if px[target]>ma20 else '跌破'}")
