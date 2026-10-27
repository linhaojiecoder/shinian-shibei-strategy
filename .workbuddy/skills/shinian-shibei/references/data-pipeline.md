# 数据流与脚本职责

## 完整数据流

```
腾讯原始 kline 接口（不复权，拆分/分红跳空保留）
        │
        ▼
backtest_data/prices_true_nofq.json   ← 权威不复权历史价（唯一成交价来源）
        │
        ▼
sim_v4.py  （诚实版回测：不复权成交 + 拆分同步调整 + 两套分红假设）
        │
        ▼
backtest_data/sim_v4.json   （含 nav_series / hold_series / trades / summary）
        │
        ▼
gen_data_full.py  （导出 App 与 skill 共用的最终数据）
        │
        ▼
app_1.0/src/data.json   （含 latest_state.holdings 精确 shares+cost + data_version）
        │
        ├──→ Electron App（continuity.js 直接读精确值接续）
        └──→ shinian-shibei skill（复盘读同一个文件）
```

## 各脚本职责

| 脚本 | 职责 | 输出 |
|------|------|------|
| `sim_v4.py` | 核心回测引擎，诚实口径 | `backtest_data/sim_v4.json` |
| `gen_data_full.py` | 把回测结果转成 App/skill 共用格式 | `app_1.0/src/data.json` |
| `rebuild_true_nofq.py` | 重建/刷新不复权历史价 | `backtest_data/prices_true_nofq.json` |

## 关键字段说明

### sim_v4.json 结构
```
{
  "cash_dividend":    { nav_series, hold_series, trades, summary, ... },
  "reinvest_dividend":{ ... }
}
```
- `cash_dividend` = 分红现金入账（实盘真实口径，App 用这个）
- `reinvest_dividend` = 分红再投入（理论口径，对应 qfq/hfq）

### hold_series 每个元素（关键！根治成本失真的地方）
```json
{
  "date": "2026-10-23",
  "holds":   { "标普500ETF": 12345678.0 },   // 市值（旧字段，兼容）
  "holdings":{ "标普500ETF": {"shares": 9876543.0, "cost": 1.258} }  // 精确份额+成本价（新字段）
}
```

### latest_state（gen_data_full.py 导出）
```json
{
  "total": ..., "nav": ..., "cash": ..., "market": ...,
  "holds_label": {...},          // 市值
  "holdings": {...}              // 精确 shares + cost ← App 直接读这个
}
```

## 数据口径红线（每条都不能破）

1. 成交价 = 不复权真实价（`prices_true_nofq.json`），禁用 qfq/hfq
2. 拆分日锚定到「拆分后首个交易日」，开盘成交前调整 shares×ratio、cost÷ratio
3. 期末持仓精确 shares+cost 直接导出，禁止从流水反推
4. data_version 每改口径 +1，触发 App 强制重接续

## 已验证的正确基准值（2026-10-27）

| 指标 | 值 |
|------|-----|
| 累计收益 | 950.71% |
| 期末总资产 | ¥31,522,111 |
| 年化 | 20.33% |
| 最大回撤 | -14.11% |
| 夏普 | 1.26 |
