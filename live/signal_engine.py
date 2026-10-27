# -*- coding: utf-8 -*-
"""
十二年十倍复利策略 · 信号引擎（实盘与回测共用同一份核心逻辑）

策略规则（与 sim_full_v3.py 完全一致）：
  - 标的：5 只 ETF
     510300 沪深300 / 159915 创业板 / 513100 纳指 / 513500 标普500 / 518880 黄金
  - 无止损
  - 双周调仓：每两个周五（索引 (i//5)%2==0）收盘算信号，下一交易日开盘成交
  - 20 日动量选 TOP2，且须动量>0、20日波动率<=2%（VOL_LIMIT）
  - 波动率目标：用「组合自身净值」近 20 日年化波动算仓位系数
      scale = clamp(15% / ann_vol, 0, 1)，只在双周调仓日计算一次
  - TOP2 内部等权

本文件是「纯函数」信号计算，不读文件、不发网络，便于回测与实盘复用。
"""
from datetime import datetime

# ---------- 策略常量（与回测一致，勿随意改动） ----------
ETFS = [
    ("510300", "沪深300"),
    ("159915", "创业板"),
    ("513100", "纳指"),
    ("513500", "标普500"),
    ("518880", "黄金"),
]
NAMES = [c for c, _ in ETFS]
LABEL = {c: n for c, n in ETFS}

MD = 20            # 动量窗口
VOL_N = 20         # 个股波动率窗口
VOL_LIMIT = 0.02   # 个股波动过滤阈值
TOP_K = 2          # 持仓数量
VOL_TARGET = 0.15  # 目标年化波动
VOL_WIN = 20       # 组合净值波动计算窗口
TRADING_DAYS = 244
ANNF = TRADING_DAYS ** 0.5


def is_friday(d):
    """判断某日期（'YYYY-MM-DD'）是否为周五。"""
    return datetime.strptime(d, "%Y-%m-%d").weekday() == 4


def is_biweekly_rebalance(i):
    """按交易日索引 i 判断是否为双周调仓日。

    与回测的 (i // 5) % 2 == 0 完全一致：i 是「当日日期在全体交易日序列中的位置」。
    注意：这里的 i 必须是「从某个固定起点连续编号的交易日索引」，
    实盘调用时需传当前日期在本地完整交易日序列中的索引，否则判定会漂移。
    """
    return (i // 5) % 2 == 0


def calc_daily_vol(rets):
    """由日收益率列表算「日」波动率（标准差，不年化）。

    回测中个股过滤 VOL_LIMIT=0.02 用的是日波动率，必须与回测保持一致。
    """
    if len(rets) < 2:
        return 0.0
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / len(rets)
    return var ** 0.5


def calc_ann_vol(rets):
    """由日收益率列表算「年化」波动率（仅用于组合净值波动率目标）。"""
    return calc_daily_vol(rets) * ANNF


def compute_signal(close, nav_arr, nav_now=None):
    """核心信号计算（纯函数）。

    参数
    ----
    close : dict[code -> list[(date, close_price)]]
        每只 ETF 的「完整」日线收盘价序列（按日期升序），
        最后一天必须是「信号计算日 T」的收盘价。
    nav_arr : list[float]
        组合自身的历史净值序列（截至 T-1 日，不含当日）。
    nav_now : float | None
        T 日收盘后的组合当前净值（= 总资产/本金）。
        回测中 scale 用的是「nav_arr + [T日nav_now]」末尾 20 日，
        实盘须传入当日收盘后的净值才能与回测严格一致。传 None 则只用 nav_arr。

    返回
    ----
    dict :
      - date          信号计算日
      - index         信号日在全交易日序列中的索引
      - mom           每只 ETF 的 20 日动量 {code: float}
      - vol           每只 ETF 的 20 日「日」波动 {code: float}（过滤用，非年化）
      - target        入选标的 code 列表（已按动量降序）
      - scale         目标总仓位系数 [0,1]
      - is_rebalance  是否双周调仓日
      - note          说明（如：标的不足/未到调仓日等）
    """
    # 1) 对齐交易日
    date_sets = [set(d for d, _ in close[n]) for n in NAMES]
    dates = sorted(set.intersection(*date_sets))
    if not dates:
        return None
    T = dates[-1]
    i = len(dates) - 1  # T 日索引

    # 2) 个股动量 + 波动（只用 T 日及之前的收盘价）
    metrics = {}
    for n in NAMES:
        c = {d: p for d, p in close[n]}
        if T not in c or len(dates) <= MD:
            metrics[n] = (0.0, 999.0)
            continue
        mom = c[T] / c[dates[i - MD]] - 1
        rets = [c[dates[j]] / c[dates[j - 1]] - 1 for j in range(i - VOL_N + 1, i + 1)]
        vol = calc_daily_vol(rets)
        metrics[n] = (mom, vol)

    ranked = sorted(NAMES, key=lambda n: metrics[n][0], reverse=True)
    target = [n for n in ranked[:TOP_K] if metrics[n][0] > 0 and metrics[n][1] <= VOL_LIMIT]

    # 3) 波动率目标 scale（组合净值）
    #    回测：combined = nav_arr(截至T-1) + [T日nav_now]，取末尾 20 日算年化波动
    combined = list(nav_arr)
    if nav_now is not None:
        combined = combined + [nav_now]
    if len(combined) >= VOL_WIN + 1:
        rets = [combined[j] / combined[j - 1] - 1 for j in range(len(combined) - VOL_WIN, len(combined))]
        ann_vol = calc_ann_vol(rets)
        scale = max(0.0, min(1.0, VOL_TARGET / ann_vol)) if ann_vol > 0 else 1.0
    else:
        scale = 1.0

    note = ""
    if not target:
        note = "无标的通过动量/波动过滤（空仓）"
    elif len(target) == 1:
        note = "仅 1 只通过过滤"

    return {
        "date": T,
        "index": i,
        "mom": {n: round(metrics[n][0], 4) for n in NAMES},
        "vol": {n: round(metrics[n][1], 4) for n in NAMES},  # 日波动率（过滤用）
        "target": target,
        "scale": round(scale, 4),
        "is_rebalance": is_biweekly_rebalance(i),
        "note": note,
    }
