# -*- coding: utf-8 -*-
"""
把 2014-2015 数据完整、正确地合并进主数据，输出 prices_full_open.json
- A股3只(510300/159915/518880)：原始数据干净，直接合并
- QDII 2只(513100/513500)：场内价格僵住(零成交)，用美股指数归一化对齐重建，
  锚点用 2016-01-04 交界价，保证与现有数据无缝衔接
"""
import json, urllib.request

BASE = 'backtest_data/'

# 1. 读主数据(2016起)
main = json.load(open(BASE + 'prices_10y_open.json'))
# 2. 读2014-2015原始
old = json.load(open(BASE + 'prices_2014_2015.json'))

# 3. 拉美股指数(2014-01 ~ 2016-03)
def fetch_index(sym):
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,2014-01-01,2016-03-31,600,'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    r = urllib.request.urlopen(req, timeout=20)
    d = json.loads(r.read().decode('utf-8'))
    k = d['data'][sym]
    kl = k.get('day') or k.get('qfqday') or []
    return {x[0]: float(x[2]) for x in kl}  # date -> close

ndx = fetch_index('us.NDX')   # 纳指100 -> 513100
inx = fetch_index('us.INX')   # 标普500 -> 513500

result = {}

# ---- 处理 QDII：用指数反推复权连续价格 ----
def rebuild_qdii(etf_code, idx_map):
    """
    用指数走势重建 ETF 2014-2015 的复权价格。
    锚点：2016-01-04 主数据里 ETF 的收盘价 / 当日指数收盘价 = 跟踪比例
    反推：ETF价格(某日) = 跟踪比例 * 指数(某日)
    """
    etf_main = main[etf_code]  # 2016起, [date,[open,close]]
    # 主数据第一天
    anchor_date = etf_main[0][0]  # 2016-01-04
    anchor_etf_close = etf_main[0][1][1]
    # 找该日指数收盘
    if anchor_date not in idx_map:
        # 美股2016-01-04可能休市，向前找最近
        for d in sorted(idx_map):
            if d <= anchor_date:
                anchor_date = d
    anchor_idx = idx_map[anchor_date]
    ratio = anchor_etf_close / anchor_idx  # 跟踪比例

    # 2014-2015 原始 ETF 的交易日历
    etf_old = old[etf_code]
    dates = [r[0] for r in etf_old]  # 2014-2015 A股交易日

    rows = []
    for d in dates:
        if d in idx_map:
            close = ratio * idx_map[d]
        else:
            # 美股休市日，用前一日价格(价格不动的合理情形)
            close = rows[-1][1][1] if rows else None
            if close is None:
                close = ratio * idx_map[d]  # 兜底
        # 开盘价：用上一日收盘近似（无更精确信息，且对策略影响极小）
        if rows:
            op = rows[-1][1][1]
        else:
            op = close
        rows.append([d, [round(op, 6), round(close, 6)]])
    return rows, ratio

print('=== 重建 QDII 价格 ===')
r100, ratio100 = rebuild_qdii('513100', ndx)
r500, ratio500 = rebuild_qdii('513500', inx)
print(f'513100 纳指: 跟踪比例 {ratio100:.6f}, {len(r100)}条 {r100[0][0]}~{r100[-1][0]}')
print(f'  2014首收 {r100[0][1][1]} 2015末收 {r100[-1][1][1]}  2016首(主数据) {main["513100"][0][1][1]}')
print(f'513500 标普: 跟踪比例 {ratio500:.6f}, {len(r500)}条 {r500[0][0]}~{r500[-1][0]}')
print(f'  2014首收 {r500[0][1][1]} 2015末收 {r500[-1][1][1]}  2016首(主数据) {main["513500"][0][1][1]}')

# ---- 合并 ----
for code in main:
    if code in ('513100', '513500'):
        pre = r100 if code == '513100' else r500
        # 去掉与主数据重复的交界日（主数据从2016-01-04开始）
        pre = [x for x in pre if x[0] < main[code][0][0]]
        merged = pre + main[code]
    else:
        # A股3只：直接合并原始2014-2015 + 主数据
        pre = [x for x in old[code] if x[0] < main[code][0][0]]
        merged = pre + main[code]
    result[code] = merged

# 检查日期连续性(相邻日期是否严格递增)
print('\n=== 合并后检查 ===')
for code, rows in result.items():
    dates = [r[0] for r in rows]
    dup = len(dates) - len(set(dates))
    non_inc = sum(1 for i in range(1, len(dates)) if dates[i] <= dates[i-1])
    print(f'{code}: {len(rows)}条 {dates[0]}~{dates[-1]}, 重复{dup} 非递增{non_inc}')

json.dump(result, open(BASE + 'prices_full_open.json', 'w'), ensure_ascii=False)
print('\n已保存 backtest_data/prices_full_open.json')
