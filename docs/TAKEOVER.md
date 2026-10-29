# 慢富十倍·复利策略：接管运行手册

本文件补充根目录 `CODEX.md`。两者共同构成后续 Codex 的持久上下文；如有冲突，以 `CODEX.md` 的数据口径铁律为准。

## 唯一正式工作区

`/Users/linhaojie/WorkBuddy/2026-10-12-21-59-24`

所有策略改动、行情更新、回测、报告生成和 Git 操作只在此目录进行。不要创建或使用第二个项目副本；执行脚本前先 `cd` 到这个目录。

## 数据边界（不可突破）

1. 历史成交只使用 `backtest_data/prices_true_nofq.json` 的不复权真实价。
2. 纳指 ETF 513100 的 1:5 拆分、标普 500 ETF 513500 的 1:2 拆分，均在拆分后首个交易日的开盘成交前执行 `shares *= ratio`、`cost /= ratio`。
3. 期末持仓从 `hold_series[].holdings` 直接导出精确 `shares` 与 `cost`，不得由交易流水反推。
4. 任何数据口径改变，必须同步递增 `app_1.0/src/data.json` 的 `data_version`。

权威事件表为 `backtest_data/events_table.json`。最终应用状态为 `app_1.0/src/data.json`，其中 `latest_state.holdings` 是 App 与复盘使用的精确持仓交接数据。

## 策略版本：慢富十倍 V1·原日历基准版

用户确认以「慢富十倍 V1·原日历基准版」命名当前策略，简称「V1 原日历版」，作为未来策略迭代与对照的基准；命名不代表已批准变更正式交易策略，也不代表收益已保证。

- 标的：510300、159915、513100、513500、518880；20 日动量先排名取前两名，再要求动量为正且 20 日日波动率不超过 2%；组合目标年化波动率 15%，仓位不超过 100%。
- 原日历：五只 ETF 的共同交易日序号为 `i`，当 `i >= 20` 且为周五且 `(i // 5) % 2 == 0` 时，以当日收盘数据生成信号；下一共同交易日开盘按模型交易。此规则节假日可能跳过调仓，不等于严格每两周。
- 独立研究基准：`audit/rebuilt_backtest.py`、`audit/fresh_market_data_20261029.json`、`audit/rebuilt_backtest_results.json` 和 `audit/rebuilt_backtest_report.html`。使用重新下载的不复权行情和基金资料页事件，以 300 万元起算；开盘价模拟成交、每侧费用 0.08%、买入整手、不透支、现金分红按发放日到账。不是正式 App 的数据版本，也不是实际交易记录。
- 2014-01-15 至 2026-10-29 的独立历史模拟：累计 +1014.65%，年化 20.75%，最大回撤 -14.11%，期末约 3,343.94 万元。该数值是特定数据和假设下的模拟，不是收益承诺。固定双周、交易摩擦等对照以及局限见独立报告。
- 重要未决问题：数据源存在 11 条价格差异待权威复核；停牌、涨跌停、成交冲击和 QDII 折溢价未完整模拟；尚未完成逐日截断的完整未来数据审计和严格样本外测试。原 `sim_v4.py` 的拆分信号、负现金等问题也尚未修复，不能因为基准版命名就认定其实现正确。

以后用户提到「V1」「原日历版」时，先以本节为准；修改方案应另起版本，保留 V1 规则、数据快照和可复现结果用于比较。不得仅因历史收益较高就默认为实盘推荐。

## 日常操作协议

用户说“今天复盘”时，先判断是否 A 股交易日；休市则停止，除非用户要求查看最近交易日。交易日按此顺序运行并核对指标：

```bash
cd /Users/linhaojie/WorkBuddy/2026-10-12-21-59-24
python3 sim_v4.py
python3 gen_data_full.py
python3 gen_report_html.py
python3 ~/.workbuddy/skills/shinian-shibei/scripts/gen_review.py
```

数据流为：

```text
prices_true_nofq.json + events_table.json
  -> sim_v4.py -> backtest_data/sim_v4.json
  -> gen_data_full.py -> app_1.0/src/data.json
  -> gen_report_html.py -> backtest_data/复盘报告.html
  -> gen_review.py -> backtest_data/review_latest.{json,md}
```

首选交付物始终是 `backtest_data/复盘报告.html`；视觉采用 A 股习惯，涨红跌绿。跑完须核对累计收益、年化、最大回撤、夏普、期末总资产和精确持仓是否与上次记录自洽；出现不合理跳变即停止并排查数据口径。

## 公众号功能：已搁置

`wechat_publish/` 代码和已有产物保留，但不再运行、维护或检查。AppID、AppSecret、`config.local.json`、草稿创建和微信接口都不属于当前工作范围，也不能作为项目卡点。只有用户明确重新启用时，才恢复这项工作。

## 正式职责

1. 每日复盘：运行 `sim_v4.py`、`gen_data_full.py`、`gen_report_html.py`、`gen_review.py` 四步并交付 HTML 报告。
2. 方案与策略代码：所有改动遵守本文件的数据边界并完成相应验证。
3. Git：改动验证后自动提交并推送；若认证失效，告知用户恢复本机 GitHub 认证后再推送。

## Git 交接约定

策略或流程代码完成并验证后，自动在本正式工作区执行 `git add`、`git commit`、`git push`。提交前先检查工作区，绝不把来源不明或与本次任务无关的既有改动混进提交。使用本机 Git 凭据；若认证失效，明确告知用户处理认证后再继续推送，不循环重试或卡住。

每次新对话开始，先阅读根目录 `CODEX.md` 和本文件，检查 Git 状态，并以 `app_1.0/src/data.json` 与 `backtest_data/sim_v4.json` 的最新日期、核心指标作为当日状态基线。
