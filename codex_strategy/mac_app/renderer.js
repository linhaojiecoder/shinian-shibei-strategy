const names = {'510300':'沪深300ETF','159915':'创业板ETF','513100':'纳指ETF','513500':'标普500ETF','518880':'黄金ETF'};
const money = n => '¥' + Math.round(n).toLocaleString('zh-CN');
const pct = n => (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
const text = (id,value) => { document.getElementById(id).textContent = value; };
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
  text('asof','数据截至 '+data.asof+' · 独立历史模拟 · 更新于 '+data.generated_at.slice(0,19).replace('T',' '));
  text('total',money(s.total));text('return',pct(m.return_pct));text('cagr',pct(m.cagr_pct));text('drawdown','-'+m.max_drawdown_pct.toFixed(2)+'%');
  for(const id of ['return','cagr']) document.getElementById(id).className='value '+(m[id==='return'?'return_pct':'cagr_pct']>=0?'up':'down');
  const body=document.getElementById('holdings'); body.replaceChildren();
  for(const [code,h] of Object.entries(s.holdings)){
    const row=document.createElement('tr'); const latest=data.latest_prices[code];
    const profit=(latest/h.cost-1)*100; const vals=[names[code]||code,Number(h.shares).toLocaleString('zh-CN'),h.cost.toFixed(4),pct(profit)];
    vals.forEach((v,i)=>{const cell=document.createElement('td');cell.textContent=v;if(i===3)cell.className=profit>=0?'up':'down';row.appendChild(cell)});body.appendChild(row);
  }
  if(!Object.keys(s.holdings).length){const row=document.createElement('tr'),cell=document.createElement('td');cell.colSpan=4;cell.textContent='空仓';row.appendChild(cell);body.appendChild(row)}
  text('cash','模拟现金 '+money(s.cash)+' · 应收分红 '+money(s.receivable));
  const sig=data.latest_signal; text('signal',sig ? sig.date+'：'+(sig.selection.map(c=>names[c]).join('、')||'无入选标的')+' · 目标总仓位 '+(sig.scale*100).toFixed(1)+'%' : '暂无信号');
  draw(data.nav);
}
async function load(refresh){const button=document.getElementById('refresh');button.disabled=true;text('status',refresh?'正在下载和重新计算，请稍候…':'正在计算离线快照…');try{render(await (refresh?window.strategy.refresh():window.strategy.snapshot()));text('status',refresh?'更新完成。请核对数据日期及风险提示。':'当前为本地快照；点击按钮可更新。')}catch(e){text('status',String(e.message||e))}finally{button.disabled=false}}
document.getElementById('refresh').addEventListener('click',()=>load(true));window.addEventListener('resize',()=>{if(window.currentData)draw(window.currentData.nav)});load(false);
