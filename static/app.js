/* 织见 · 经营智能分析平台 — 前端逻辑 */
'use strict';
const $=s=>document.querySelector(s), el=i=>document.getElementById(i);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state={me:null,view:'query',jobTimer:null,charts:[],routeSeq:0};

const MENUS={
  dashboard:{name:'经营总览',icon:'M3 12l9-9 9 9M5 10v10h5v-6h4v6h5V10'},
  query:{name:'智能问数',icon:'M21 21l-4.3-4.3M11 19a8 8 0 100-16 8 8 0 000 16zM8 11h6M11 8v6'},
  analysis:{name:'经营分析',icon:'M3 17l6-6 4 4 8-8M21 7v6h-6'},
  metrics:{name:'指标中心',icon:'M4 20V10M10 20V4M16 20v-7M22 20H2'},
  reports:{name:'个人报告',icon:'M7 3h10l4 4v14H7zM10 7h8M10 11h8M10 15h5'},
  accounts:{name:'账户管理',icon:'M12 12a4 4 0 100-8 4 4 0 000 8zM4 21v-1a8 8 0 0116 0v1'}
};
const ROLES_MAP={'admin':'系统管理员','executive':'经营负责人','finance':'财务分析师','sales':'销售经理','production':'生产主管','warehouse':'仓储主管'};
const DOMAINS={'销售':'销售','财务':'财务','生产':'生产','采购':'采购','库存':'库存'};
const KIND_LABEL={
  task_start:'任务开始',plan:'分析计划',subtask_start:'子任务',schema_linking:'Schema 关联',
  embedding:'向量检索',retrieval:'召回',metric_lookup:'指标口径',sql_generate:'生成 SQL',
  sql_check:'安全校验',explain:'执行计划',sql_execute:'执行查询',result:'查询结果',answer:'生成回答',
  step:'执行步骤',error:'错误',done:'完成',llm:'模型调用'
};

/* ---------- 基础工具 ---------- */
async function api(path,opts={}){
  const r=await fetch(path,{cache:'no-store',headers:{'Content-Type':'application/json'},...opts});
  if(r.status===401){location.href='/';throw new Error('unauthorized');}
  let data={};
  try{data=await r.json();}catch(e){}
  if(!r.ok){const e=new Error(data.detail||('请求失败（'+r.status+'）'));e.status=r.status;e.data=data;throw e;}
  return data;
}
const fmtTime=ts=>{const d=new Date(ts*1000);const p=n=>String(n).padStart(2,'0');return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;};
const fmtNum=(v,d=2)=>v==null?'—':Number(v).toLocaleString('zh-CN',{minimumFractionDigits:d,maximumFractionDigits:d});
const fmtInt=v=>v==null?'—':Number(v).toLocaleString('zh-CN');

/* ---------- 初始化 ---------- */
async function init(){
  try{state.me=await api('/api/me');}catch(e){location.href='/';return;}
  renderSidebar();
  if(!location.hash||!MENUS[location.hash.slice(1)]||!state.me.menus.includes(location.hash.slice(1)))location.hash='dashboard';
  window.addEventListener('hashchange',route);
  route();
  el('btnLogout').addEventListener('click',async()=>{await api('/api/logout',{method:'POST'});location.href='/';});
  bindPasswordModal();
}
function renderSidebar(){
  const nav=el('sideNav');nav.innerHTML='';
  for(const m of state.me.menus){
    const d=MENUS[m];if(!d)continue;
    const a=document.createElement('div');a.className='nav-item';a.dataset.view=m;
    a.innerHTML=`<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="${d.icon}"/></svg>${d.name}`;
    a.addEventListener('click',()=>{location.hash=m;});
    nav.appendChild(a);
  }
  el('sidebarUser').innerHTML=`<div class="u-name">${esc(state.me.name)}</div><div class="u-role">${esc(state.me.role_name)}${state.me.region?' · '+esc(state.me.region):''}</div>`;
}
function route(){
  const view=location.hash.slice(1);
  if(!MENUS[view]||!state.me.menus.includes(view)){location.hash='dashboard';return;}
  const seq=++state.routeSeq;
  state.view=view;
  document.querySelectorAll('.nav-item').forEach(n=>n.classList.toggle('active',n.dataset.view===view));
  el('pageTitle').textContent=MENUS[view].name;
  disposeCharts();
  const fn={dashboard:renderDashboard,query:renderQuery,analysis:renderAnalysis,metrics:renderMetrics,reports:renderReports,accounts:renderAccounts}[view];
  fn().catch(e=>{if(seq!==state.routeSeq)return;el('content').innerHTML=`<div class="empty">加载失败：${esc(e.message)}</div>`;}).then(()=>{if(seq!==state.routeSeq)return;});
}
function disposeCharts(){state.charts.forEach(c=>{try{c.dispose();}catch(e){}});state.charts=[];}
function chart(id,option){
  const dom=el(id);if(!dom||!window.echarts)return null;
  const c=echarts.init(dom);c.setOption(option);state.charts.push(c);
  return c;
}

/* ---------- 经营总览 ---------- */
async function renderDashboard(){
  const seq=state.routeSeq;
  const d=await api('/api/dashboard');
  if(seq!==state.routeSeq)return;
  const c=el('content');
  const kpiHtml=k=>Object.entries(k).map(([k2,v],i)=>{
    const meta={batches:['生产批次','批','green'],output_meters:['实际产量','米','accent'],yield_pct:['良品率','%','green'],plan_pct:['计划达成率','%','amber'],
      stock_meters:['期末库存','米','accent'],stock_value:['库存金额','元','green'],aged_meters:['库龄 90 天以上','米','amber'],aged_pct:['库龄占比','%','red'],
      revenue:['营业收入','元','accent'],gross_profit:['毛利','元','green'],orders:['订单数','单','blue'],meters:['销售数量','米','amber']};
    const m=meta[k2]||[k2,'',''];const cls=i===0?'accent':'';
    return `<div class="kpi-card ${m[2]||cls}"><div class="k-label">${m[0]}</div><div class="k-value">${fmtNum(v,m[1]==='元'||m[1]==='米'?0:2)}${m[1]?'<span style="font-size:13px;color:#66788c;margin-left:4px">'+m[1]+'</span>':''}</div></div>`;
  }).join('');
  let body='';
  if(d.view==='production'){
    body=`<div class="kpi-grid">${kpiHtml(d.kpi)}</div>
      <div class="card"><div class="card-title">生产视角说明</div>
      <p style="color:#66788c;line-height:1.8">本视图面向生产主管，展示<b>生产批次、实际产量、良品率与计划达成率</b>。数据来源：production_batches（模拟数据）。
      成本类字段对生产岗位隐藏；销售、财务明细不在本岗位权限范围内。</p></div>`;
  }else if(d.view==='warehouse'){
    body=`<div class="kpi-grid">${kpiHtml(d.kpi)}</div>
      <div class="card"><div class="card-title">仓储视角说明</div>
      <p style="color:#66788c;line-height:1.8">本视图面向仓储主管，展示<b>期末库存数量、库存金额、库龄 90 天以上数量与占比</b>。库存金额用于盘点对账（对仓储可见）；
      销售金额、成本字段对仓储岗位隐藏。</p></div>`;
  }else{
    body=`<div class="kpi-grid">${kpiHtml(d.kpi)}</div>
      <div class="grid-2">
        <div class="card"><div class="card-title">月度收入与毛利趋势（按交付日期）</div><div class="chart-box" id="chTrend"></div></div>
        <div class="card"><div class="card-title">产品收入贡献</div><div class="chart-box" id="chProducts"></div></div>
      </div>
      <div class="card"><div class="card-title">库存摘要</div>
        <div class="kpi-grid" style="margin-bottom:0">${kpiHtml({stock_meters:d.inventory.stock,aged_meters:d.inventory.aged})}</div>
      </div>`;
  }
  c.innerHTML=`<div class="card" style="display:flex;align-items:center;justify-content:space-between">
      <div><span class="badge badge-blue">模拟数据</span> <span style="color:#66788c;margin-left:10px">统计区间：${esc(d.period)}</span></div>
      <div style="color:#66788c;font-size:13px">${esc(state.me.role_name)}${d.region?' · '+esc(d.region):''}</div>
    </div>${body}`;
  if(d.view!=='production'&&d.view!=='warehouse'){
    const months=d.trend.map(t=>t.month);
    chart('chTrend',{
      tooltip:{trigger:'axis'},
      legend:{data:['营业收入','毛利']},
      grid:{left:60,right:20,top:40,bottom:30},
      xAxis:{type:'category',data:months},
      yAxis:{type:'value',axisLabel:{formatter:v=>(v/10000)+'万'}},
      series:[
        {name:'营业收入',type:'bar',data:d.trend.map(t=>Math.round(t.revenue)),itemStyle:{color:'#2f6fed'},barMaxWidth:22},
        {name:'毛利',type:'line',data:d.trend.map(t=>Math.round(t.gross_profit??0)),itemStyle:{color:'#22a06b'},smooth:true}
      ]
    });
    chart('chProducts',{
      tooltip:{trigger:'axis',axisPointer:{type:'shadow'}},
      grid:{left:130,right:30,top:16,bottom:24},
      xAxis:{type:'value',axisLabel:{formatter:v=>(v/10000)+'万'}},
      yAxis:{type:'category',data:d.products.map(p=>p.product_name)},
      series:[{type:'bar',data:d.products.map(p=>Math.round(p.revenue)),itemStyle:{color:'#2f6fed'},barMaxWidth:18}]
    });
  }
}

/* ---------- 智能问数 / 经营分析 ---------- */
function queryTemplate(mode){
  return `<div class="card">
    <div class="card-title">描述你想了解的经营问题</div>
    <div style="margin-top:14px" class="query-bar">
      <textarea class="text-input" id="question" placeholder="${mode==='query'?'例：华东区域 6 月营业收入是多少？按产品汇总':'例：分析本月经营情况，找出销售与库存的主要问题并提出建议'}"></textarea>
      <button class="btn-primary" id="btnSubmit" style="align-self:flex-end">提交问题</button>
    </div>
    <div style="color:#66788c;font-size:12px;margin-top:8px">系统先理解问题，再查询数据或分步分析。请写明指标和期间；每次提交为独立问题，暂不承接上一问的省略信息。</div>
  </div>
  <div id="jobPanel"></div>`;
}
async function renderQuery(){renderQueryView('query');}
async function renderAnalysis(){renderQueryView('analysis');}
async function renderQueryView(mode){
  const c=el('content');
  c.innerHTML=queryTemplate(mode);
  const run=async()=>{
    const q=el('question').value.trim();
    if(!q){el('jobPanel').innerHTML=`<div class="empty">请输入问题</div>`;return;}
    el('btnSubmit').disabled=true;
    el('jobPanel').innerHTML=`<div class="card"><div class="spin"></div>任务已提交，正在执行…</div>`;
    try{
      const {id}=await api('/api/jobs',{method:'POST',body:JSON.stringify({question:q,mode:'auto'})});
      pollJob(id);
    }catch(e){el('jobPanel').innerHTML=`<div class="empty">提交失败：${esc(e.message)}</div>`;el('btnSubmit').disabled=false;}
  };
  el('btnSubmit').addEventListener('click',run);
  el('question').addEventListener('keydown',e=>{if(e.ctrlKey&&e.key==='Enter')run();});
}
function pollJob(id){
  if(state.jobTimer)clearInterval(state.jobTimer);
  let last=null;
  const tick=async()=>{
    let j;
    try{j=await api('/api/jobs/'+id);}catch(e){stop();el('jobPanel').innerHTML=`<div class="empty">任务查询失败：${esc(e.message)}</div>`;return;}
    if(JSON.stringify(j)!==last){last=JSON.stringify(j);renderJob(j);}
    if(['completed','failed','partial','needs_clarification'].includes(j.status)){
      stop();if(el('btnSubmit'))el('btnSubmit').disabled=false;
    }
  };
  const stop=()=>{if(state.jobTimer){clearInterval(state.jobTimer);state.jobTimer=null;}};
  tick();state.jobTimer=setInterval(tick,1500);
}
function renderJob(j){
  const p=el('jobPanel');if(!p)return;
  const statusBadge={queued:'badge-gray',running:'badge-blue',completed:'badge-green',failed:'badge-red',partial:'badge-amber'}[j.status]||'badge-gray';
  const statusName={queued:'排队中',running:'执行中',completed:'已完成',failed:'失败',partial:'部分完成',needs_clarification:'请补充信息'}[j.status]||j.status;
  const tl=(j.events||[]).map(e=>{
    const label=({understanding:'理解问题',understood:'问题理解完成'})[e.kind]||KIND_LABEL[e.kind]||e.kind;
    const cls=e.kind==='error'?'err':(e.kind==='result'||e.kind==='done'||e.kind==='answer')?'ok':'';
    return `<div class="tl-item"><div class="tl-dot ${cls}"></div><div class="tl-body">
      <div class="tl-title">${esc(label)}${e.message?'<span style="font-weight:400;color:#66788c"> · '+esc(e.message)+'</span>':''}</div>
      <div class="tl-detail">${fmtTime(e.time)}${e.extra&&e.extra.step?' · 步骤 '+esc(e.extra.step):''}</div></div></div>`;
  }).join('');
  let results='';
  if(j.results&&j.results.length){
    results=j.results.map(r=>{
      const head=`步骤 ${r.step.id}：${esc(r.step.title)}${r.success?'':'（执行失败）'}`;
      if(!r.success)return `<div class="result-card"><div class="result-head">${head}</div><div class="result-body"><div class="sql-block">${esc(r.sql||'')}</div><div style="color:#d64545;margin-top:8px">${esc(r.error||'')}</div></div></div>`;
      const cols=r.columns||(r.rows&&r.rows.length?Object.keys(r.rows[0]):[]);
      const headRow=cols.map(c=>`<th>${esc(c)}</th>`).join('');
      const bodyRows=(r.rows||[]).slice(0,100).map(row=>`<tr>${cols.map(c=>`<td class="${/amount|price|value|cost|revenue|profit|pct/i.test(c)?'num':''}">${esc(row[c]??'')}</td>`).join('')}</tr>`).join('');
      const truncated=(r.rows||[]).length>100?`<tr><td colspan="${cols.length}" style="color:#66788c">仅显示前 100 行，共 ${r.rows.length} 行</td></tr>`:'';
      return `<div class="result-card"><div class="result-head">${head}<span class="collapse-link" data-t="sql-${r.step.id}">SQL 与依据</span></div>
        <div class="result-body" id="sql-${r.step.id}" hidden><div class="sql-block">${esc(r.sql||'')}</div>${r.explain?`<div style="margin-top:8px;color:#66788c;font-size:12px">执行计划：<span class="mono">${esc(String(r.explain).slice(0,200))}</span></div>`:''}</div>
        <div class="result-body"><div class="table-wrap"><table class="data"><thead><tr>${headRow}</tr></thead><tbody>${bodyRows}${truncated}</tbody></table></div></div></div>`;
    }).join('');
  }
  const report=j.report?`<div class="card"><div class="card-title">${j.status==='needs_clarification'?'需要补充的信息':'分析报告'}
    ${j.status==='needs_clarification'?'':`<a class="btn-ghost btn-sm" href="/api/jobs/${j.id}/report">下载 Markdown</a>`}</div>
    <div class="report-box">${esc(j.report)}</div></div>`:'';
  const error=j.error?`<div class="card" style="border-color:#f5c6c6"><div class="card-title" style="color:#d64545">执行失败</div><div>${esc(j.error)}</div></div>`:'';
  const q=el('question')?el('question').value:j.question;
  p.innerHTML=`<div class="card" style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
      <span class="badge ${statusBadge}">${statusName}</span>
      <span style="font-weight:600">${esc(q)}</span>
      <span style="color:#66788c;font-size:12px">${j.mode==='analysis'?'经营分析':'智能问数'} · ${fmtTime(j.created_at||(Date.now()/1000))}${j.duration_seconds!=null?' · 耗时 '+j.duration_seconds+'s':''}</span>
    </div>
    ${error}${report}
    <div class="card"><div class="card-title">执行过程</div>${tl||'<div class="empty">暂无过程记录</div>'}</div>
    ${results?'<div class="card"><div class="card-title">查询结果</div>'+results+'</div>':''}`;
  p.querySelectorAll('.collapse-link').forEach(a=>a.addEventListener('click',()=>{
    const t=el(a.dataset.t);t.hidden=!t.hidden;a.textContent=t.hidden?'SQL 与依据':'收起 SQL 与依据';
  }));
  // 自动滚动到任务面板
  p.scrollIntoView({behavior:'smooth',block:'start'});
}

/* ---------- 指标中心 ---------- */
async function renderMetrics(){
  const seq=state.routeSeq;
  const m=await api('/api/metrics');
  if(seq!==state.routeSeq)return;
  const c=el('content');
  c.innerHTML=`<div class="card">
    <div class="card-title">指标知识库
      <div style="display:flex;gap:10px;align-items:center">
        <select class="text-input" id="mDomain" style="width:auto"><option value="">全部领域</option>${Object.keys(DOMAINS).map(d=>`<option>${d}</option>`).join('')}</select>
        <input class="text-input" id="mSearch" placeholder="搜索指标名称/编码" style="width:220px">
      </div>
    </div>
    <div style="color:#66788c;font-size:12px;margin-bottom:12px">共 ${m.total} 条治理指标；每条包含定义、公式、时间口径、负责人与版本。可见性按岗位权限控制。</div>
    <div class="table-wrap"><table class="data" id="mTable">
      <thead><tr><th>编码</th><th>指标名称</th><th>领域</th><th>定义</th><th>计算公式</th><th>单位</th><th>时间口径</th><th>维度</th><th>负责人</th><th>版本</th><th>状态</th><th>本岗位可见</th></tr></thead>
      <tbody></tbody></table></div>
  </div>`;
  const tb=m.items;
  const draw=()=>{
    const dom=el('mDomain').value, kw=el('mSearch').value.trim().toLowerCase();
    const rows=tb.filter(i=>(!dom||i.domain===dom)&&(!kw||(i.name||'').toLowerCase().includes(kw)||(i.code||'').toLowerCase().includes(kw)));
    el('mTable').querySelector('tbody').innerHTML=rows.map(i=>`<tr>
      <td class="mono">${esc(i.code)}</td><td style="font-weight:600">${esc(i.name)}</td>
      <td><span class="badge badge-blue">${esc(i.domain)}</span></td>
      <td style="max-width:280px">${esc(i.definition)}</td>
      <td style="max-width:240px"><span class="mono">${esc(i.formula)}</span></td>
      <td>${esc(i.unit)}</td><td>${esc(i.time_field)}</td>
      <td>${esc((i.dimensions||[]).join('、'))}</td><td>${esc(i.owner)}</td>
      <td>v${esc(i.version)}</td>
      <td><span class="badge ${i.status==='published'?'badge-green':'badge-gray'}">${i.status==='published'?'已发布':esc(i.status)}</span></td>
      <td>${i.visible?'<span class="badge badge-green">可见</span>':'<span class="badge badge-gray">不可见</span>'}</td>
    </tr>`).join('')||'<tr><td colspan="12" class="empty">无匹配指标</td></tr>';
  };
  el('mDomain').addEventListener('change',draw);el('mSearch').addEventListener('input',draw);
  draw();
}

/* ---------- 个人报告 ---------- */
async function renderReports(){
  const seq=state.routeSeq;
  const h=await api('/api/history');
  if(seq!==state.routeSeq)return;
  const c=el('content');
  c.innerHTML=`<div class="card"><div class="card-title">我的查询与分析记录</div>
    <div id="reportList"></div></div><div id="reportDetail"></div>`;
  const list=el('reportList');
  if(!h.length){list.innerHTML='<div class="empty">暂无记录，去「智能问数」或「经营分析」发起第一个任务吧</div>';return;}
  list.innerHTML=h.map(j=>`<div class="history-item">
    <span class="badge ${j.status==='completed'?'badge-green':j.status==='failed'?'badge-red':j.status==='partial'?'badge-amber':'badge-blue'}">${{queued:'排队中',running:'执行中',completed:'已完成',failed:'失败',partial:'部分完成'}[j.status]||j.status}</span>
    <div style="flex:1;min-width:0"><div class="history-q">${esc(j.question)}</div><div class="history-meta">${j.mode==='analysis'?'经营分析':'智能问数'}</div></div>
    <button class="btn-ghost btn-sm" data-view="${j.id}">查看详情</button>
  </div>`).join('');
  list.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',async()=>{
    try{const j=await api('/api/jobs/'+b.dataset.view);renderJobDetail(j);}catch(e){el('reportDetail').innerHTML=`<div class="empty">${esc(e.message)}</div>`;}
  }));
}
function renderJobDetail(j){
  const d=el('reportDetail');
  const results=(j.results||[]).map(r=>{
    if(!r.success)return `<div class="result-card"><div class="result-head">步骤 ${r.step.id}：${esc(r.step.title)}（失败）</div><div class="result-body"><div class="sql-block">${esc(r.sql||'')}</div><div style="color:#d64545;margin-top:8px">${esc(r.error||'')}</div></div></div>`;
    const cols=r.columns||(r.rows&&r.rows.length?Object.keys(r.rows[0]):[]);
    return `<div class="result-card"><div class="result-head">步骤 ${r.step.id}：${esc(r.step.title)}</div>
      <div class="result-body"><div class="table-wrap"><table class="data"><thead><tr>${cols.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead>
      <tbody>${(r.rows||[]).slice(0,50).map(row=>`<tr>${cols.map(c=>`<td>${esc(row[c]??'')}</td>`).join('')}</tr>`).join('')}</tbody></table></div></div></div>`;
  }).join('');
  d.innerHTML=`<div class="card"><div class="card-title">${esc(j.question)}
      <a class="btn-ghost btn-sm" href="/api/jobs/${j.id}/report">下载 Markdown 报告</a></div>
    ${j.report?`<div class="report-box">${esc(j.report)}</div>`:''}
    ${results?'<div style="margin-top:16px">'+results+'</div>':''}
    ${j.error?`<div style="color:#d64545;margin-top:12px">${esc(j.error)}</div>`:''}</div>`;
  d.scrollIntoView({behavior:'smooth'});
}

/* ---------- 账户管理 ---------- */
async function renderAccounts(){
  const seq=state.routeSeq;
  const {users}=await api('/api/admin/users');
  if(seq!==state.routeSeq)return;
  const c=el('content');
  c.innerHTML=`<div class="card">
    <div class="card-title">企业账户管理<button class="btn-primary btn-sm" id="btnNewUser">+ 新建用户</button></div>
    <div style="color:#66788c;font-size:12px;margin-bottom:12px">权限同时约束菜单、数据表、敏感字段与数据区域。密码使用 PBKDF2 加盐哈希存储。</div>
    <div class="table-wrap"><table class="data">
      <thead><tr><th>ID</th><th>用户名</th><th>姓名</th><th>岗位</th><th>数据区域</th><th>状态</th><th>创建时间</th><th>最近登录</th><th style="width:150px">操作</th></tr></thead>
      <tbody>${users.map(u=>`<tr>
        <td>${u.user_id}</td><td class="mono">${esc(u.username)}</td><td>${esc(u.display_name)}</td>
        <td><span class="badge badge-blue">${esc(ROLES_MAP[u.role]||u.role)}</span></td>
        <td>${esc(u.region||'—')}</td>
        <td>${u.active?'<span class="badge badge-green">启用</span>':'<span class="badge badge-gray">停用</span>'}</td>
        <td>${u.created_at?esc(String(u.created_at).slice(0,16)):'—'}</td>
        <td>${u.last_login_at?esc(String(u.last_login_at).slice(0,16)):'—'}</td>
        <td style="white-space:nowrap">
          <button class="btn-ghost btn-sm" data-edit="${u.user_id}">编辑</button>
          <button class="btn-ghost btn-sm btn-danger" data-toggle="${u.user_id}" data-active="${u.active?1:0}">${u.active?'停用':'启用'}</button>
        </td></tr>`).join('')}</tbody>
    </table></div>
  </div>`;
  el('btnNewUser').addEventListener('click',()=>openUserModal(null));
  c.querySelectorAll('[data-edit]').forEach(b=>b.addEventListener('click',()=>{
    const u=users.find(x=>x.user_id==b.dataset.edit);openUserModal(u);
  }));
  c.querySelectorAll('[data-toggle]').forEach(b=>b.addEventListener('click',async()=>{
    const id=b.dataset.toggle;const next=b.dataset.active==='1'?false:true;
    try{await api('/api/admin/users/'+id,{method:'PATCH',body:JSON.stringify({active:next})});renderAccounts();}
    catch(e){alert(e.message);}
  }));
}
function openUserModal(u){
  el('userModalTitle').textContent=u?'编辑用户：'+u.username:'新建用户';
  el('userEditId').value=u?u.user_id:'';
  el('uUsername').value=u?u.username:'';el('uUsername').disabled=!!u;
  el('uDisplay').value=u?u.display_name:'';
  el('uRole').innerHTML=Object.entries(ROLES_MAP).map(([k,v])=>`<option value="${k}" ${u&&u.role===k?'selected':''}>${v}</option>`).join('');
  el('uRegion').value=u?(u.region||''):'';
  el('uPassword').value='';
  el('uPwdLabel').textContent=u?'重置密码（留空则不修改）':'初始密码（至少 6 位）';
  el('uError').hidden=true;
  el('uRole').onchange=()=>{el('uRegionLabel').style.display=el('uRole').value==='sales'?'block':'none';el('uRegion').style.display=el('uRole').value==='sales'?'block':'none';};
  el('uRole').onchange();
  el('userModal').hidden=false;
}
async function bindUserModal(){
  const close=()=>{el('userModal').hidden=true;};
  document.querySelectorAll('[data-close]').forEach(b=>b.addEventListener('click',()=>{el(b.dataset.close).hidden=true;}));
  el('userModal').addEventListener('click',e=>{if(e.target===el('userModal'))close();});
  el('uSave').addEventListener('click',async()=>{
    const id=el('userEditId').value;
    const body={display_name:el('uDisplay').value.trim(),role:el('uRole').value,region:el('uRegion').value||null};
    const err=el('uError');
    try{
      if(id){await api('/api/admin/users/'+id,{method:'PATCH',body:JSON.stringify(body)});}
      else{
        if(!el('uUsername').value.trim())throw new Error('请输入用户名');
        if(el('uPassword').value.length<6)throw new Error('初始密码至少 6 位');
        await api('/api/admin/users',{method:'POST',body:JSON.stringify({...body,username:el('uUsername').value.trim(),password:el('uPassword').value})});
      }
      if(el('uPassword').value.length>=6&&id){
        await api('/api/admin/users/'+id,{method:'PATCH',body:JSON.stringify({password:el('uPassword').value})}).catch(()=>{});
      }
      close();renderAccounts();
    }catch(e){err.textContent=e.message;err.hidden=false;}
  });
}
function bindPasswordModal(){
  const close=()=>{el('passwordModal').hidden=true;};
  document.querySelectorAll('[data-close]').forEach(b=>b.addEventListener('click',()=>{el(b.dataset.close).hidden=true;}));
  el('passwordModal').addEventListener('click',e=>{if(e.target===el('passwordModal'))close();});
  el('btnPassword').addEventListener('click',()=>{el('pwError').hidden=true;el('pwOld').value=el('pwNew').value=el('pwNew2').value='';el('passwordModal').hidden=false;});
  el('pwSave').addEventListener('click',async()=>{
    const err=el('pwError');
    try{
      if(el('pwNew').value.length<6)throw new Error('新密码至少 6 位');
      if(el('pwNew').value!==el('pwNew2').value)throw new Error('两次输入的新密码不一致');
      await api('/api/password',{method:'POST',body:JSON.stringify({old_password:el('pwOld').value,new_password:el('pwNew').value})});
      alert('密码已修改');close();
    }catch(e){err.textContent=e.message;err.hidden=false;}
  });
}

document.addEventListener('DOMContentLoaded',async()=>{bindUserModal();init();});
