# 慢富十倍·复利策略：接管运行手册

本文件补充根目录 `CODEX.md`。两者共同构成后续 Codex 的持久上下文；如有冲突，以 `CODEX.md` 的数据口径铁律为准。

## 唯一正式工作区

`/Users/linhaojie/WorkBuddy/2026-10-12-21-59-24`

所有策略改动、行情更新、回测、报告生成、公众号草稿和 Git 操作只在此目录进行。不要创建或使用第二个项目副本；执行脚本前先 `cd` 到这个目录。

## 数据边界（不可突破）

1. 历史成交只使用 `backtest_data/prices_true_nofq.json` 的不复权真实价。
2. 纳指 ETF 513100 的 1:5 拆分、标普 500 ETF 513500 的 1:2 拆分，均在拆分后首个交易日的开盘成交前执行 `shares *= ratio`、`cost /= ratio`。
3. 期末持仓从 `hold_series[].holdings` 直接导出精确 `shares` 与 `cost`，不得由交易流水反推。
4. 任何数据口径改变，必须同步递增 `app_1.0/src/data.json` 的 `data_version`。

权威事件表为 `backtest_data/events_table.json`。最终应用状态为 `app_1.0/src/data.json`，其中 `latest_state.holdings` 是 App、复盘和公众号使用的精确持仓交接数据。

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

## 公众号协议

用户说“发公众号”时，先运行：

```bash
cd /Users/linhaojie/WorkBuddy/2026-10-12-21-59-24
python3 wechat_publish/publish.py --dry
```

将生成的文章和封面给用户确认。只有用户明确确认后才运行：

```bash
python3 wechat_publish/publish.py
```

正式建草稿需要 `wechat_publish/config.local.json`，其中必须有微信公众平台 `AppID` 与 `AppSecret`；该文件不得提交。脚本只建立草稿，不替用户发表。`published_lock.json` 用于当天幂等去重，除非用户明确要求，不使用 `--force`。

## Git 交接约定

策略或流程代码完成并验证后，自动在本正式工作区执行 `git add`、`git commit`、`git push`。提交前先检查工作区，绝不把来源不明或与本次任务无关的既有改动混进提交。使用本机 Git 凭据；若认证失效，明确告知用户处理认证后再继续推送，不循环重试或卡住。

每次新对话开始，先阅读根目录 `CODEX.md` 和本文件，检查 Git 状态，并以 `app_1.0/src/data.json` 与 `backtest_data/sim_v4.json` 的最新日期、核心指标作为当日状态基线。
