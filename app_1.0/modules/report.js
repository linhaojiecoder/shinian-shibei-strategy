// 日报写入：写每日模拟盘日报（供 WorkBuddy 自动化读取推送到微信）
const path = require('path');
const os = require('os');
const fs = require('fs');
const eng = require('../engine.js');

// 日报路径（原样保留）
const DAILY_REPORT = path.join(os.homedir(), '.shinian-shibei', '日报.md');

let ctx = null;

// 注入共享上下文（state / lastSignal 均可变，经 ctx 取最新引用）
function init(_ctx) {
  ctx = _ctx;
}

// ---------- 写每日模拟盘日报（供 WorkBuddy 自动化读取推送到微信） ----------
function writeDailyReport(todayTrades) {
  const { state, lastSignal } = ctx;
  try {
    const r = lastSignal;
    if (!r) return;
    const { sig, latest, closeOn, navNow } = r;
    const nav = eng.currentNav(state, closeOn);
    const total = state.cash + Object.keys(state.holdings).reduce((s, c) => s + state.holdings[c].shares * (closeOn[c] || 0), 0);

    const lines = [];
    lines.push(`## 慢富十倍 · 模拟盘日报 ${latest}`);
    lines.push('');
    lines.push(`当前净值 **${nav.toFixed(4)}**（起步本金 ¥3,000,000）`);
    lines.push(`总资产 ¥${Math.round(total).toLocaleString()}｜现金 ¥${Math.round(state.cash).toLocaleString()}`);

    // 持仓
    const hc = Object.keys(state.holdings);
    if (hc.length === 0) {
      lines.push('当前持仓：**空仓**');
    } else {
      lines.push('当前持仓：');
      for (const c of hc) {
        const h = state.holdings[c];
        const v = h.shares * (closeOn[c] || 0);
        lines.push(`  - ${eng.LABEL[c]}：${h.shares.toLocaleString()} 份 × ¥${(closeOn[c] || 0).toFixed(3)} ≈ ¥${Math.round(v).toLocaleString()}`);
      }
    }

    // 今日模拟交易
    if (todayTrades && todayTrades.length) {
      lines.push('');
      lines.push('**今日模拟成交：**');
      for (const t of todayTrades) {
        lines.push(`  - ${t.action} ${t.label}（${t.code}）${t.shares.toLocaleString()} 份 @ ¥${t.price}`);
      }
    }

    // 信号
    lines.push('');
    lines.push('五标的信号（20日动量）：');
    for (const e of eng.ETFS) {
      lines.push(`  - ${e.label}：${(sig.mom[e.code] * 100).toFixed(2)}%（${sig.target.includes(e.code) ? '★持有' : '-'}）`);
    }
    lines.push(`目标仓位 scale = **${(sig.scale * 100).toFixed(0)}%**`);
    if (sig.note) lines.push(`⚠ ${sig.note}`);

    // 调仓日提示
    if (sig.isRebalance) {
      lines.push('');
      lines.push('### 📌 今日为双周调仓日，模拟盘已自动调仓（下一交易日开盘成交）');
      lines.push(`目标：${sig.target.map(c => eng.LABEL[c]).join(' + ') || '空仓'}，仓位 ${(sig.scale * 100).toFixed(0)}%`);
    }

    lines.push('');
    lines.push('---');
    lines.push('_模拟盘，仅供参考，不构成投资建议。_');

    fs.mkdirSync(path.dirname(DAILY_REPORT), { recursive: true });
    fs.writeFileSync(DAILY_REPORT, lines.join('\n'), 'utf8');
    console.log('日报已写入', DAILY_REPORT);
  } catch (e) {
    console.error('写日报失败:', e);
  }
}

module.exports = { init, writeDailyReport };
