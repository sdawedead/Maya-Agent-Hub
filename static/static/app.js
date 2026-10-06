const names={business_hunter:'BUSINESS HUNTER',job_hunter:'JOB HUNTER',server_caretaker:'SERVER CARETAKER',network_watcher:'NETWORK WATCH',land_hunter:'LAND HUNTER',photo_librarian:'PHOTO LIBRARIAN',nomadic_content:'NOMADIC CONTENT',research_agent:'RESEARCH LAB',wti_integration:"MAYA'S OIL BRIDGE",maya_coordinator:'MAYA COORDINATOR'};
const esc=s=>(s??'').toString().replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
let latestStatus=null;
async function api(url,opt){const r=await fetch(url,opt);if(!r.ok)throw new Error(`${r.status} ${r.statusText}`);return r.json()}
function payloadOf(a){let p=a?.last?.payload||{};if(typeof p==='string'){try{p=JSON.parse(p)}catch{p={raw:p}}}return p||{}}
function renderDetails(key){
 const a=latestStatus?.agents?.find(x=>x.key===key); if(!a)return;
 const p=payloadOf(a); const rows=[];
 if(Array.isArray(p.items)&&p.items.length){rows.push(`<h3>RESULTS</h3><div class="detail-list">`+p.items.map((x,i)=>`<a class="detail-item" href="${esc(x.url||'#')}" target="_blank" rel="noopener"><b>${i+1}. ${esc(x.title||x.name||'Result')}</b><span>${x.score!=null?`Score ${esc(x.score)}`:x.match!=null?`Match ${esc(x.match)}`:''}${x.provider?` • ${esc(x.provider)}`:''}</span><small>${esc(x.url||'')}</small></a>`).join('')+`</div>`)}
 if(Array.isArray(p.services)){rows.push(`<h3>SERVICES</h3><div class="detail-list">`+p.services.map(x=>`<div class="detail-item"><b>${esc(x.name)} — ${x.ok?'ONLINE':'DOWN'}</b><span>Port ${esc(x.port)}${x.latency_ms!=null?` • ${esc(x.latency_ms)} ms`:''}</span></div>`).join('')+`</div>`)}
 if(Array.isArray(p.folders)){rows.push(`<h3>PHOTO FOLDERS</h3><div class="detail-list">`+p.folders.map(x=>`<div class="detail-item"><b>${esc(x.path)}</b><span>${x.exists?'FOUND':'MISSING'} • ${esc(x.photos)} photos • ${esc(x.gb)} GB</span></div>`).join('')+`</div>`)}
 if(p.disk){rows.push(`<h3>NETWORK / SERVER</h3><div class="detail-item"><b>${esc(p.hostname||'Server')}</b><span>Disk ${esc(p.disk.used_pct)}% used • ${esc(p.disk.free_gb)} GB free</span>${p.tailscale_ip?`<small>Tailscale ${esc(p.tailscale_ip)}</small>`:''}</div>`)}
 if(Array.isArray(p.next_actions)){rows.push(`<h3>NEXT ACTIONS</h3><div class="detail-list">`+p.next_actions.map(x=>`<div class="detail-item">${esc(x)}</div>`).join('')+`</div>`)}
 if(Array.isArray(p.errors)&&p.errors.length){rows.push(`<h3 class="err">SOURCE ERRORS</h3><div class="detail-list">`+p.errors.map(x=>`<div class="detail-item errorbox"><b>${esc(x.query||'source')}</b><small>${esc(x.error||'Unknown error')}</small></div>`).join('')+`</div>`)}
 if(!rows.length){rows.push(`<pre>${esc(JSON.stringify(p,null,2))}</pre>`)}
 document.getElementById('detailTitle').textContent=names[key]||a.title||key;
 document.getElementById('detailSummary').textContent=a.last?.summary||'No run yet.';
 document.getElementById('detailBody').innerHTML=rows.join('');
 document.getElementById('modal').classList.add('show');
}
function closeModal(){document.getElementById('modal').classList.remove('show')}
async function refresh(){
 const s=await api('/api/status'); latestStatus=s; document.getElementById('clock').textContent=new Date(s.time).toLocaleString(); document.getElementById('version').textContent=s.version||'2.1'; const tu=document.getElementById('tailscaleUrl'); if(s.access_urls?.tailscale){tu.textContent='TAILSCALE: '+s.tailscale_ip;tu.href=s.access_urls.tailscale;tu.classList.remove('mutedlink')}else{tu.textContent='TAILSCALE: not detected';tu.href='#';tu.classList.add('mutedlink')}
 document.getElementById('onlineCount').textContent=s.agents.filter(a=>a.enabled).length;
 document.getElementById('workingCount').textContent=s.agents.filter(a=>a.running).length;
 const alerts=s.agents.filter(a=>a.last&&(a.last.status!=='ok'||(a.last.summary||'').startsWith('DOWN:'))).length;
 document.getElementById('alertCount').textContent=alerts;
 document.getElementById('grid').innerHTML=s.agents.map(a=>{
  let st=a.running?'WORKING':!a.enabled?'DISABLED':a.last?.status==='error'?'ERROR':'ONLINE'; let cls=a.running?'idle':st==='ERROR'?'err':'ok';
  return `<article class="card"><span class="badge ${cls}">${st}</span><h3>${esc(names[a.key]||a.title)}</h3><div class="meta">${a.interval_minutes?`AUTO • ${a.interval_minutes} min`:'MANUAL'}</div><div class="summary">${esc(a.last?.summary||'Ready. No run yet.')}</div><div class="card-actions"><button onclick="runAgent('${a.key}')">RUN NOW</button><button class="secondary" onclick="renderDetails('${a.key}')" ${a.last?'':'disabled'}>DETAILS</button></div></article>`
 }).join('');
 const h=await api('/api/runs?limit=14');
 document.getElementById('history').innerHTML=h.runs.map(r=>`<div class="run"><time>${esc(r.finished_at||r.started_at)}</time><b>${esc(names[r.agent]||r.agent)}</b><span class="${r.status==='ok'?'ok':'err'}">${esc(r.summary||r.status)}</span></div>`).join('')||'<div class="meta">No activity yet.</div>';
}
async function runAgent(k,body={}){await api('/api/run/'+k,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});setTimeout(refresh,700)}
document.getElementById('runAll').onclick=()=>runAgent('all');
document.getElementById('researchBtn').onclick=()=>runAgent('research_agent',{query:document.getElementById('researchQuery').value});
document.getElementById('modalClose').onclick=closeModal;document.getElementById('modal').onclick=e=>{if(e.target.id==='modal')closeModal()};
refresh();setInterval(refresh,5000);
