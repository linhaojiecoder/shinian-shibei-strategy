const names = {'510300':'沪深300ETF','159915':'创业板ETF','513100':'纳指ETF','513500':'标普500ETF','518880':'黄金ETF'};
const money = n => '¥' + Math.round(n).toLocaleString('zh-CN');
const signedMoney = n => (n >= 0 ? '+' : '−') + money(Math.abs(n));
const pct = n => (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
const text = (id,value) => { document.getElementById(id).textContent = value; };
const color = n => n >= 0 ? 'up' : 'down';
function draw(rows) {
  const canvas=document.getElementById('chart'), ratio=window.devicePixelRatio||1;
  const rect=canvas.getBoundingClientRect(); canvas.width=rect.width*ratio; canvas.height=rect.height*ratio;
  const ctx=canvas.getContext('2d'); ctx.scale(ratio,ratio); const w=rect.width,h=rect.height,p=12;
  const values=rows.map(x=>x.total), lo=Math.min(...values), hi=Math.max(...values), span=hi-lo||1;
  ctx.strokeStyle='#34445a';ctx.beginPath();ctx.moveTo(p,h-p);ctx.lineTo(w-p,h-p);ctx.stroke();
  ctx.strokeStyle='#efc46c';ctx.lineWidth=2;ctx.beginPath();
  values.forEach((v,i)=>{const x=p+(w-2*p)*i/(values.length-1), y=h-p-(h-2*p)*(v-lo)/span;i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();
}
function render(data) {
  window.currentData=data; const m=data.metrics,s=data.state;
  text('asof','数据截至 '+data.asof+' · 独立历史模拟 · 计算于 '+data.generated_at.slice(0,19).replace('T',' '));
  text('total',money(s.total));text('return',pct(m.return_pct));text('cagr',pct(m.cagr_pct));text('drawdown','−'+m.max_drawdown_pct.toFixed(2)+'%');
  text('daily',signedMoney(data.daily_change)+' / '+pct(data.daily_change_pct));text('market',money(s.market));text('cash',money(s.cash));text('weight',(s.market/s.total*100).toFixed(1)+'%');
  for(const [id,val] of [['return',m.return_pct],['cagr',m.cagr_pct],['daily',data.daily_change]]) document.getElementById(id).className='value '+color(val);
  const body=document.getElementById('holdings'); body.replaceChildren();
  for(const [code,h] of Object.entries(s.holdings)){
    const row=document.createElement('tr'), d=data.position_details[code], latest=data.latest_prices[code];
    const profit=(latest/h.cost-1)*100;
    const vals=[names[code]||code,money(d.market),signedMoney(d.profit)+' / '+pct(profit),Number(h.shares).toLocaleString('zh-CN'),h.cost.toFixed(4)+' / '+latest.toFixed(4),d.daily_profit===null?'—':signedMoney(d.daily_profit),(d.weight*100).toFixed(1)+'%',d.holding_days+' 天'];
    vals.forEach((v,i)=>{const cell=document.createElement('td');cell.textContent=v;if(i===2)cell.className=color(d.profit);if(i===5&&d.daily_profit!==null)cell.className=color(d.daily_profit);row.appendChild(cell)});body.appendChild(row);
  }
  if(!Object.keys(s.holdings).length){const row=document.createElement('tr'),cell=document.createElement('td');cell.colSpan=8;cell.textContent='空仓';row.appendChild(cell);body.appendChild(row)}
  text('receivable','模拟应收分红 '+money(s.receivable)+'；已计入总资产，未计入可用现金。');
  const sig=data.latest_signal; text('signal',sig ? sig.date+'：'+(sig.selection.map(c=>names[c]).join('、')||'无入选标的')+' · 目标总仓位 '+(sig.scale*100).toFixed(1)+'%' : '暂无信号');
  const cards=document.getElementById('scores');cards.replaceChildren();
  for(const [code,score] of Object.entries(data.scores)){
    const card=document.createElement('div');card.className='signal-card'+(s.holdings[code]?' held':'');
    for(const [value,klass] of [[names[code]+(s.holdings[code]?' · 模拟持有':''),''],[pct(score.momentum*100),color(score.momentum)],['日波动 '+(score.volatility*100).toFixed(2)+'%','muted'],['收盘价 '+score.price.toFixed(3),'muted']]){const line=document.createElement('div');line.textContent=value;line.className=klass;card.appendChild(line)}cards.appendChild(card);
  }
  draw(data.nav);
}
let loading=false;
async function load(refresh){if(loading)return;loading=true;const button=document.getElementById('refresh');button.disabled=true;text('status',refresh?'正在下载和重新计算，请稍候…':'正在计算本地快照…');try{render(await (refresh?window.strategy.refresh():window.strategy.snapshot()));text('status',refresh?'更新完成。请核对数据日期及风险提示。':'已载入本地快照，即将自动更新。')}catch(e){text('status','更新失败，保留上次结果：'+String(e.message||e))}finally{button.disabled=false;loading=false}}
document.getElementById('refresh').addEventListener('click',()=>load(true));window.addEventListener('resize',()=>{if(window.currentData)draw(window.currentData.nav)});
window.strategy.onResume(()=>load(true));
(async()=>{await load(false);await load(true);})();setInterval(()=>load(true),60*60*1000);
