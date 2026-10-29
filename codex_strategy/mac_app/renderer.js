const names = {'510300':'沪深300ETF','159915':'创业板ETF','513100':'纳指ETF','513500':'标普500ETF','518880':'黄金ETF'};
const money = n => '¥' + Math.round(n).toLocaleString('zh-CN');
const signedMoney = n => (n >= 0 ? '+' : '−') + money(Math.abs(n));
const pct = n => (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
const text = (id,value) => { document.getElementById(id).textContent = value; };
const color = n => n >= 0 ? 'up' : 'down';
let chartGeometry=null;
function draw(rows, selected=null) {
  const canvas=document.getElementById('chart'), ratio=window.devicePixelRatio||1;
  const rect=canvas.getBoundingClientRect(); canvas.width=rect.width*ratio; canvas.height=rect.height*ratio;
  const ctx=canvas.getContext('2d'); ctx.scale(ratio,ratio); const w=rect.width,h=rect.height;
  const left=65,right=18,top=18,bottom=34, values=rows.map(x=>(x.total/3000000-1)*100);
  const lo=Math.floor(Math.min(0,...values)/100)*100, hi=Math.ceil(Math.max(1,...values)/100)*100, span=hi-lo||1;
  const x=i=>left+(w-left-right)*i/(values.length-1), y=v=>top+(h-top-bottom)*(hi-v)/span;
  ctx.font='11px -apple-system, sans-serif';ctx.fillStyle='#9caec4';ctx.strokeStyle='#34445a';ctx.lineWidth=1;
  for(let j=0;j<=4;j++){const v=lo+span*j/4, py=y(v);ctx.beginPath();ctx.moveTo(left,py);ctx.lineTo(w-right,py);ctx.stroke();ctx.textAlign='right';ctx.fillText(v.toFixed(0)+'%',left-8,py+4)}
  ctx.textAlign='center';for(let j=0;j<=4;j++){const i=Math.round((rows.length-1)*j/4), px=x(i);ctx.fillText(rows[i].date,px,h-8)}
  ctx.strokeStyle='#efc46c';ctx.lineWidth=2;ctx.beginPath();
  values.forEach((v,i)=>{i?ctx.lineTo(x(i),y(v)):ctx.moveTo(x(i),y(v))});ctx.stroke();
  if(selected!==null){const px=x(selected),py=y(values[selected]);ctx.strokeStyle='#99a9bd';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(px,top);ctx.lineTo(px,h-bottom);ctx.stroke();ctx.fillStyle='#efc46c';ctx.beginPath();ctx.arc(px,py,4,0,2*Math.PI);ctx.fill()}
  chartGeometry={left,right,width:w,rows};
}
function render(data) {
  window.currentData=data; const m=data.metrics,s=data.state;
  text('asof','数据截至 '+data.asof+' · 独立历史模拟 · 计算于 '+data.generated_at.slice(0,19).replace('T',' '));
  text('total',money(s.total));text('return',pct(m.return_pct));text('cagr',pct(m.cagr_pct));text('drawdown','−'+m.max_drawdown_pct.toFixed(2)+'%');
  text('daily-amount',signedMoney(data.daily_change));text('daily-pct',pct(data.daily_change_pct));text('market',money(s.market));text('cash',money(s.cash));text('weight',(s.market/s.total*100).toFixed(1)+'%');
  for(const [id,val] of [['return',m.return_pct],['cagr',m.cagr_pct],['daily',data.daily_change]]) document.getElementById(id).className='value '+color(val);
  const body=document.getElementById('holdings'); body.replaceChildren();
  for(const [code,h] of Object.entries(s.holdings)){
    const row=document.createElement('tr'), d=data.position_details[code], latest=data.latest_prices[code];
    const profit=(latest/h.cost-1)*100;
    const vals=[names[code]||code,money(d.market),signedMoney(d.profit)+' / '+pct(profit),Number(h.shares).toLocaleString('zh-CN'),h.cost.toFixed(4)+' / '+latest.toFixed(4),d.daily_profit===null?'—':signedMoney(d.daily_profit),(d.weight*100).toFixed(1)+'%',d.holding_days+' 天'];
    vals.forEach((v,i)=>{const cell=document.createElement('td');cell.textContent=v;if(i===2)cell.className=color(d.profit);if(i===5&&d.daily_profit!==null)cell.className=color(d.daily_profit);row.appendChild(cell)});body.appendChild(row);
  }
  if(!Object.keys(s.holdings).length){const row=document.createElement('tr'),cell=document.createElement('td');cell.colSpan=8;cell.textContent='空仓';row.appendChild(cell);body.appendChild(row)}
  const pending=data.pending_signal;
  text('next-action',pending ? '信号日期 '+pending.date+'；下一共同交易日开盘模拟调仓。目标：'+(pending.selection.map(c=>names[c]).join('、')||'空仓')+'，目标总仓位 '+(pending.selection.length?(pending.scale*100).toFixed(1):'0.0')+'%。具体买卖数量以执行日模型计算为准。' : '预计下一信号日 '+data.candidate_signal_date+'（假设此后工作日均为共同交易日，节假日或停牌可能改变）；买什么须等信号日收盘计算，随后下一共同交易日开盘模拟执行。');
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
const canvas=document.getElementById('chart'), tip=document.getElementById('chart-tip');
canvas.addEventListener('pointermove',event=>{if(!chartGeometry)return;const rect=canvas.getBoundingClientRect(),g=chartGeometry;const i=Math.max(0,Math.min(g.rows.length-1,Math.round((event.clientX-rect.left-g.left)/(g.width-g.left-g.right)*(g.rows.length-1))));const row=g.rows[i],prev=g.rows[i-1];draw(g.rows,i);tip.textContent=row.date+'  累计收益 '+pct((row.total/3000000-1)*100)+'  当日收益 '+(prev?pct((row.total/prev.total-1)*100):'—')+'  模拟资产 '+money(row.total);tip.hidden=false;});
canvas.addEventListener('pointerleave',()=>{tip.hidden=true;if(window.currentData)draw(window.currentData.nav)});
window.strategy.onResume(()=>load(true));
(async()=>{await load(false);await load(true);})();setInterval(()=>load(true),60*60*1000);
