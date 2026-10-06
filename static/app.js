const names={business_hunter:'BUSINESS HUNTER',job_hunter:'JOB HUNTER',server_caretaker:'SERVER CARETAKER',network_watcher:'NETWORK WATCH',land_hunter:'LAND HUNTER',photo_librarian:'PHOTO LIBRARIAN',nomadic_content:'NOMADIC CONTENT',research_agent:'RESEARCH LAB',wti_integration:"MAYA'S OIL BRIDGE",maya_coordinator:'MAYA COORDINATOR'};
const esc=s=>(s??'').toString().replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
async function api(url,opt){const r=await fetch(url,opt);return r.json()}
async function refresh(){
 const s=await api('/api/status'); document.getElementById('clock').textContent=new Date(s.time).toLocaleString(); document.getElementById('version').textContent=s.version||'2.0'; const tu=document.getElementById('tailscaleUrl'); if(s.access_urls?.tailscale){tu.textContent='TAILSCALE: '+s.tailscale_ip;tu.href=s.access_urls.tailscale;tu.classList.remove('mutedlink')}else{tu.textContent='TAILSCALE: not detected';tu.href='#';tu.classList.add('mutedlink')}
 document.getElementById('onlineCount').textContent=s.agents.filter(a=>a.enabled).length;
 document.getElementById('workingCount').textContent=s.agents.filter(a=>a.running).length;
 const alerts=s.agents.filter(a=>a.last&&(a.last.status!=='ok'||(a.last.summary||'').startsWith('DOWN:'))).length;
 document.getElementById('alertCount').textContent=alerts;
 document.getElementById('grid').innerHTML=s.agents.map(a=>{
  let st=a.running?'WORKING':!a.enabled?'DISABLED':a.last?.status==='error'?'ERROR':'ONLINE'; let cls=a.running?'idle':st==='ERROR'?'err':'ok';
  return `<article class="card"><span class="badge ${cls}">${st}</span><h3>${esc(names[a.key]||a.title)}</h3><div class="meta">${a.interval_minutes?`AUTO • ${a.interval_minutes} min`:'MANUAL'}</div><div class="summary">${esc(a.last?.summary||'Ready. No run yet.')}</div><button onclick="runAgent('${a.key}')">RUN NOW</button></article>`
 }).join('');
 const h=await api('/api/runs?limit=14');
 document.getElementById('history').innerHTML=h.runs.map(r=>`<div class="run"><time>${esc(r.finished_at||r.started_at)}</time><b>${esc(names[r.agent]||r.agent)}</b><span class="${r.status==='ok'?'ok':'err'}">${esc(r.summary||r.status)}</span></div>`).join('')||'<div class="meta">No activity yet.</div>';
}
async function runAgent(k,body={}){await api('/api/run/'+k,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});setTimeout(refresh,400)}
document.getElementById('runAll').onclick=()=>runAgent('all');
document.getElementById('researchBtn').onclick=()=>runAgent('research_agent',{query:document.getElementById('researchQuery').value});
refresh();setInterval(refresh,5000);
