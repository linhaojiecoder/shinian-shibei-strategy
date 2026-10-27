---
name: shinian-shibei
description: >-
  「十二年十倍复利策略」专属复盘与持仓管理。运行本地回测脚本更新净值/持仓/成本，生成复盘报告，写入 Obsidian 知识库。
  触发词：十二年十倍、复盘、持仓、净值、调仓信号、今日操作、策略复盘、收益核对、成本核对。
agent_created: true
version: 1.0.0
display_name: "十二年十倍复利策略"
display_name_zh: "十二年十倍复利策略"
display_name_en: "Shinian Shibei Strategy"
description_zh: "十二年十倍复利策略的每日复盘、持仓成本核对、净值更新与调仓信号，输出内联 HTML 报告并写入 Obsidian。"
description_en: "Daily review, holdings/cost verification, NAV update and rebalance signals for the Shinian-Shibei strategy."
visibility: "private"
---

# 十二年十倍复利策略 · 复盘与持仓管理

## 这是什么

一个只服务你本人的 A 股 ETF 动量轮动策略（五年标的：沪深300ETF 510300、创业板ETF 159915、纳指ETF 513100、标普500ETF 513500、黄金ETF 518880），双周调仓，目标「慢慢变富，与时间为友」。

本 skill 让你**不开 App** 也能在对话里完成每日复盘、核对持仓成本、看调仓信号。数据与 Electron App **共用同一套文件**，两边永远一致。

## 最重要的一条铁律（数据口径护栏）

历史上反复出现「收益对不上」的 bug，根源只有一个：**数据口径混乱**。以下规则必须逐条遵守，任何一步都不能省略：

1. **只用「不复权真实价」（nofq）成交**，绝不混用 qfq/hfq。
   - 权威数据源文件：`backtest_data/prices_true_nofq.json`（腾讯原始 kline 接口产出，拆分/分红跳空完整保留）。
   - 注意：westock 的复权功能是坏的（bfq 实际等于 qfq、nofq 数据错乱、bfq 报错），**禁止用 westock 拿历史复权价**。实时现价可以用 westock/qt.gtimg.cn，但历史回测只能用 `prices_true_nofq.json`。

2. **份额拆分必须锚定到「拆分后首个交易日」**，且在该日开盘成交之前调整份额。
   - 拆分公告日（纳指 2022-01-13 做 1:5、标普 2022-03-29 做 1:2）是停牌日，不在交易日序列里，直接按日期匹配永远失效。
   - 正确做法（见 `sim_v4.py` 的 `split_trigger`）：`shares *= ratio`，`cost /= ratio`，总资产不变。

3. **期末持仓的精确 shares + cost 必须直接导出**，绝不能从交易流水反推。
   - 流水价格是不复权价，跨拆分点反推会把拆分前旧价与拆分后新价混加权，导致成本价严重失真（历史 bug 根源，曾算出「标普成本 2.664 > 现价 2.563 却显示 +3.96%」的荒谬结果）。
   - `sim_v4.py` 的 `hold_series` 已带 `holdings` 字段（精确 shares + cost），`gen_data_full.py` 已把它写进 `latest_state.holdings`，`continuity.js` 直接读精确值。

4. **`data_version` 每改一次数据口径 +1**，触发 App 强制重新接续，杜绝旧口径残留。

## 数据文件（与 App 共享，绝对路径）

| 文件 | 作用 |
|------|------|
| `backtest_data/prices_true_nofq.json` | 权威不复权历史价（唯一成交价来源） |
| `backtest_data/events_table.json` | 权威事件表（拆分 1:5/1:2、现金分红） |
| `backtest_data/sim_v4.json` | 诚实版回测结果（两套分红假设） |
| `app_1.0/src/data.json` | App 与 skill 共用的最终数据（含 latest_state.holdings + data_version） |
| `~/.shinian-shibei/state.json` | 实盘模拟盘状态（App 运行时维护） |

> 项目根目录固定为：`/Users/linhaojie/WorkBuddy/2026-10-12-21-59-24/`
> 所有脚本以该目录为基准运行。

## 运行流程（复盘 = 四步）

### 第一步：检查交易日

判断今天是否为 A 股交易日。周末或法定节假日休市时，直接告知「今日休市」，停止（除非用户明确要看最近一个交易日的数据）。

### 第二步：更新行情 + 跑回测

```bash
cd /Users/linhaojie/WorkBuddy/2026-10-12-21-59-24
# 1. 拉最新不复权行情（如需刷新 prices_true_nofq.json，用腾讯 kline 接口；已有缓存则跳过）
# 2. 跑诚实版回测
python3 sim_v4.py
# 3. 导出 App/skill 共用的 data.json
python3 gen_data_full.py
```

运行后核对打印输出的关键指标：累计收益、年化、回撤、夏普、期末总资产。这些值必须与 `obsidian-vault/03-每日沟通日志/` 里上次记录自洽（跨日波动应在合理范围，若出现跳变说明数据口径又出了问题，立即停下排查）。

### 第三步：生成复盘报告

读 `sim_v4.json` 与 `app_1.0/src/data.json`，产出复盘内容（内联 HTML 看板或 Markdown，按用户偏好），至少包含：
- 净值/总资产/现金/持仓市值（精确持仓 + 成本价）
- 累计收益、年化、回撤、夏普
- 当前持仓（label、份额、成本价、现价、浮动盈亏%）
- 调仓信号（动量前2 + 波动率筛选）
- 与沪深300 基准对比

### 第四步：写入 Obsidian 知识库

把当日复盘追加到 `obsidian-vault/03-每日沟通日志/YYYY-MM-DD.md`（若无则新建），并同步更新 `obsidian-vault/02-项目细节/十二年十倍复利策略.md` 里的「最新状态」小节。

## 关键口径速查

- 成本价 = 加权平均买入成本（含手续费 0.08%），拆分日 `cost /= ratio`
- 浮动盈亏 = (现价 - 成本) / 成本
- 现价来源：腾讯 `qt.gtimg.cn`（f[3]=现价、f[4]=昨收、f[31]=涨跌幅），或 westock 实时接口
- 净值 = (现金 + Σ份额×现价) / 本金 3,000,000
- 双周调仓：周五触发，动量前 2 且 `mom>0 且 vol≤2%`，目标波动率 15%

## 参考文件

- `references/data-pipeline.md` — 完整数据流与各脚本职责
- `references/events-table.md` — 权威事件表（拆分/分红）明细
