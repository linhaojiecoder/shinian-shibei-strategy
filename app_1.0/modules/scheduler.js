// 定时器调度：每日收盘定时更新 + 盘中实时刷新调度 + 交易日判定
const eng = require('../engine.js');

let timer = null;         // 每日 15:05 收盘更新定时器
let intradayTimer = null; // 盘中每 5 分钟实时刷新定时器

// ---------- 交易日判定 ----------
// 接收 Date 对象，转成 'YYYY-MM-DD' 后调用 engine 的精确判定（周末 + 法定节假日均休市）
function isTradingDay(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return eng.isTradingDay(`${y}-${m}-${dd}`);
}
function isTradingHours(d) {
  const h = d.getHours(), m = d.getMinutes();
  const t = h * 60 + m;
  return t >= 9 * 60 + 30 && t <= 15 * 60; // 9:30 ~ 15:00
}

// ---------- 定时刷新（每交易日 15:05） ----------
function scheduleNext(runUpdate) {
  if (timer) clearTimeout(timer);
  const now = new Date();
  const next = new Date(now);
  next.setHours(15, 5, 0, 0);
  if (next <= now) next.setDate(next.getDate() + 1);
  const ms = next - now;
  timer = setTimeout(() => { runUpdate(); scheduleNext(runUpdate); }, ms);
  console.log(`下次自动更新: ${next.toLocaleString('zh-CN')}`);
}

// ---------- 盘中实时刷新（每 5 分钟，交易日 9:30-15:00） ----------
function scheduleIntraday(refreshIntraday) {
  if (intradayTimer) clearTimeout(intradayTimer);
  intradayTimer = setTimeout(() => { refreshIntraday(); scheduleIntraday(refreshIntraday); }, 5 * 60 * 1000);
}

// 退出前清理定时器
function clearTimers() {
  if (timer) clearTimeout(timer);
  if (intradayTimer) clearTimeout(intradayTimer);
}

module.exports = { isTradingDay, isTradingHours, scheduleNext, scheduleIntraday, clearTimers };
