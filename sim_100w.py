import json, math

with open("backtest_data/prices.json") as f:
    data = json.load(f)
names = ["510300", "159915", "513100", "518880"]
date_sets = [set(d for d, _ in data[n]) for n in names]
common_dates = sorted(set.intersection(*date_sets))
prices = {n: {d: v for d, v in data[n]} for n in names}
label = {"510300":"沪深300","159915":"创业板","513100":"纳指","518880":"黄金"}

last_date = common_dates[-1]
i = len(common_dates) - 1
print(f"交易日: {last_date}")
print()

# 100万本金
CAPITAL = 1_000_000

# 今天信号：全仓纳指
# 纳指ETF 513100 今收 2.345
nq_price = prices["513100"][last_date]
print(f"纳指ETF(513100)今日收盘价: {nq_price:.3f} 元/份")
print(f"本金: ¥{CAPITAL:,}")
print()

# ETF交易单位: 100份一手
lots = int(CAPITAL / (nq_price * 100)) * 100
cost = lots * nq_price
cash_remain = CAPITAL - cost
print(f"可买份额(按100份整数手): {lots:,} 份")
print(f"买入成本: ¥{cost:,.2f}")
print(f"剩余现金(不足一手): ¥{cash_remain:,.2f}")
print()

# 参考历史: 如果从回测起点(2021-02-23)就投入100万，今天变成多少
# 直接从之前回测的最终净值反推
final_nav = 6.4853  # 2026-10-19 的累计净值(从 detail_report.py)
print("="*50)
print("【参考】如果2021年2月就按此策略投入100万:")
print(f"  期末总资产: ¥{CAPITAL * final_nav:,.0f}  (约{(final_nav-1)*100:.0f}%收益)")
print(f"  5年净赚: ¥{CAPITAL*(final_nav-1):,.0f}")
print()
print("【但这是回测理想值，实盘打对折都不止，别当真】")

# 分年度100万滚动的资金曲线
years_nav = [1.1607, 1.4333, 1.9687, 2.7036, 4.8750, 6.4853]
years = ["2021","2022","2023","2024","2025","2026"]
print()
print("【100万按回测年度滚动】")
print(f"{'年度':<8}{'年初资产':>14}{'年度收益':>10}{'年末资产':>14}")
prev = CAPITAL
for y, nav in zip(years, years_nav):
    year_ret = nav/years_nav[years.index(y)-1]-1 if years.index(y)>0 else nav-1
    end = CAPITAL * nav
    print(f"{y:<8}{prev:>14,.0f}{year_ret*100:>9.1f}%{end:>14,.0f}")
    prev = end
