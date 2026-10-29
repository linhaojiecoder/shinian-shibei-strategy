# CODEX.md

> 本文件是给 Codex（以及任何后续接手的 AI）看的项目使用说明。
> 项目：**慢富十倍·复利策略**（A 股 ETF 动量轮动，双周调仓）。

## 一句话定位

一个只服务用户本人的 A 股 ETF 复利策略体系，包含：数据回测、每日复盘报告（HTML）与策略迭代。核心诉求是「慢慢变富，与时间为友」，数据必须**永远自洽**（历史上反复出现「收益对不上」的 bug）。

## 项目根目录

```
/Users/linhaojie/WorkBuddy/2026-10-12-21-59-24
```

所有脚本都以这个目录为基准运行（绝对路径）。数据与 Electron App、WorkBuddy skill 共用同一套文件，两边永远一致。

## 目录速查

| 路径 | 作用 |
|------|------|
| `app_1.0/src/data.json` | **最终数据源**（含 latest_state.holdings 精确持仓 + data_version），App 与复盘共用 |
| `backtest_data/prices_true_nofq.json` | 权威不复权历史价（唯一成交价来源，腾讯 kline 产出） |
| `backtest_data/events_table.json` | 权威事件表（份额拆分 1:5 / 1:2、现金分红） |
| `backtest_data/sim_v4.json` | 诚实版回测结果 |
| `backtest_data/复盘报告.html` | 每日复盘报告（HTML，首选交付物） |
| `gen_data_full.py` | 跑回测后导出 App/skill 共用的 data.json |
| `gen_report_html.py` | 生成复盘报告 HTML |
| `sim_v4.py` | 诚实版回测引擎（含 split_trigger 拆分处理） |
| `wechat_publish/` | 公众号旧功能，已搁置；文件保留但不运行、不维护、不配置 |
| `~/.workbuddy/skills/shinian-shibei/` | WorkBuddy skill（含 SKILL.md 数据口径铁律） |

## 数据口径铁律（最重要，违反必出 bug）

历史上反复出现「收益对不上」的 bug，根源只有一个：**数据口径混乱**。以下规则逐条遵守，不能省：

1. **只用「不复权真实价」（nofq）成交**，绝不混用 qfq/hfq。权威源 = `backtest_data/prices_true_nofq.json`。禁止用 westock 拿历史复权价（它的复权功能是坏的）；实时现价可用 `qt.gtimg.cn` 或 westock。
2. **份额拆分锚定到「拆分后首个交易日」**，并在该日开盘成交前调份额。拆分公告日（纳指 2022-01-13 做 1:5、标普 2022-03-29 做 1:2）是停牌日，不在交易日序列里。正确做法见 `sim_v4.py` 的 `split_trigger`：`shares *= ratio`，`cost /= ratio`，总资产不变。
3. **期末持仓的精确 shares + cost 直接导出**，绝不从交易流水反推（跨拆分点反推会把新旧价混加权，成本价严重失真）。精确值已在 `latest_state.holdings`。
4. **`data_version` 每改一次口径 +1**，触发 App 强制重接续。

## 每日复盘标准流程（四步）

```bash
cd /Users/linhaojie/WorkBuddy/2026-10-12-21-59-24

# 第一步：判断今天是否 A 股交易日（周末/节假日休市则停止，除非用户要看最近交易日）
# 第二步：更新行情 + 跑回测
python3 sim_v4.py
python3 gen_data_full.py
# 第三步：生成 HTML 复盘报告（首选交付物）
python3 gen_report_html.py        # → backtest_data/复盘报告.html
# 第四步：生成 Markdown 复盘（写 Obsidian）
python3 ~/.workbuddy/skills/shinian-shibei/scripts/gen_review.py
```

跑完核对打印输出的关键指标（累计收益/年化/回撤/夏普/期末总资产），必须与 `obsidian-vault/03-每日沟通日志/` 上次记录自洽。若跨日跳变异常，说明口径又出问题，立即停下排查。

## 公众号功能：已搁置

`wechat_publish/` 相关的 AppID、AppSecret、`config.local.json`、文章/封面生成和微信草稿均不属于当前交付目标，也不作为任何流程的前置条件或卡点。保留现有文件，不删除；除非用户明确重新启用，否则不运行、不维护、不检查该目录。

## 当前正式职责

1. 每日复盘：按本文件规定的四步流程生成并核对结果。
2. 方案与策略代码：按四条数据口径铁律改动、验证。
3. Git 交接：代码或流程改动验证后自动 `git add`、`git commit`、`git push`；若本机 Git 认证失效，明确提醒用户处理认证，不反复重试或卡住。

## 关键口径速查

- 成本价 = 加权平均买入成本（含手续费 0.08%），拆分日 `cost /= ratio`
- 浮动盈亏 = (现价 - 成本) / 成本
- 净值 = (现金 + Σ份额×现价) / 本金 3,000,000
- 双周调仓：周五触发，动量前 2 且 `mom>0 且 vol≤2%`，目标波动率 15%
- 五年标的：沪深300ETF 510300、创业板ETF 159915、纳指ETF 513100、标普500ETF 513500、黄金ETF 518880
- A 股涨红跌绿（红色=涨，绿色=跌），与美股相反

## 用户偏好

- 直接、说真话，不要客套和废话，不要「好问题」「我很乐意」这类开场白
- 要有观点和判断，不要平铺多种可能让用户自己选
- 首选交付物是 HTML 报告（深色金融风、红涨绿跌），不要纯 Markdown（白底黑字不好看）
- 每次代码改动自动推 GitHub，不用问
