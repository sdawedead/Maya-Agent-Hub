(() => {
  if (window.__mayaAgentCardLoaded) return;
  window.__mayaAgentCardLoaded = true;

  const hubUrl = `${location.protocol}//${location.hostname}:8065/`;

  function findCardGrid() {
    const needles = ["STORAGE NETWORK", "MAYA'S OIL AGENT", "SERVER MONITOR", "BIOSWARE CINEMA"];
    const all = [...document.querySelectorAll('article,a,div,section')];
    for (const needle of needles) {
      const hit = all.find(el => {
        const t = (el.textContent || '').trim().toUpperCase();
        if (!t.includes(needle)) return false;
        const r = el.getBoundingClientRect();
        return r.width > 150 && r.width < 700 && r.height > 80 && r.height < 700;
      });
      if (!hit) continue;
      let card = hit;
      for (let i=0; i<5 && card.parentElement; i++, card=card.parentElement) {
        const cls = String(card.className || '').toLowerCase();
        if (card.tagName === 'ARTICLE' || cls.includes('card')) break;
      }
      const parent = card.parentElement;
      if (parent) {
        const d = getComputedStyle(parent).display;
        if ((d === 'grid' || d === 'flex') && parent.children.length >= 2) return parent;
      }
    }
    return null;
  }

  function addCard() {
    if (document.getElementById('maya-agent-hub-portal-card')) return true;
    const grid = findCardGrid();
    const a = document.createElement('a');
    a.id = 'maya-agent-hub-portal-card';
    a.href = hubUrl;
    a.innerHTML = `
      <div class="mah-orbit"></div>
      <div class="mah-kicker"><span class="mah-dot"></span> ONLINE</div>
      <div class="mah-icon">✦</div>
      <div class="mah-title">MAYA COMMAND CENTER</div>
      <div class="mah-sub">Agents • Automation • Intelligence</div>
      <div class="mah-open">OPEN →</div>`;

    const style = document.createElement('style');
    style.textContent = `
      #maya-agent-hub-portal-card{position:relative;overflow:hidden;min-height:220px;padding:22px;text-decoration:none;color:#eef7ff;border:1px solid rgba(91,187,255,.42);border-radius:22px;background:radial-gradient(circle at 85% 8%,rgba(114,75,255,.35),transparent 32%),linear-gradient(145deg,rgba(6,24,52,.96),rgba(5,8,25,.98));box-shadow:0 18px 55px rgba(0,0,0,.42),inset 0 0 30px rgba(52,152,255,.08);display:flex;flex-direction:column;justify-content:flex-start;gap:8px;isolation:isolate}
      #maya-agent-hub-portal-card:hover{transform:translateY(-2px);filter:brightness(1.08)}
      #maya-agent-hub-portal-card .mah-orbit{position:absolute;width:230px;height:230px;border:1px solid rgba(92,220,255,.16);border-radius:50%;right:-100px;top:-110px;box-shadow:0 0 40px rgba(85,87,255,.2);z-index:-1}
      #maya-agent-hub-portal-card .mah-kicker{font:700 11px/1.2 Segoe UI,Arial,sans-serif;letter-spacing:.14em;color:#77ffd1}
      #maya-agent-hub-portal-card .mah-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:#6dffc2;box-shadow:0 0 12px #6dffc2;margin-right:7px}
      #maya-agent-hub-portal-card .mah-icon{font-size:28px;color:#78e7ff;text-shadow:0 0 20px #6f5dff;margin-top:6px}
      #maya-agent-hub-portal-card .mah-title{font:800 23px/1.05 Segoe UI,Arial,sans-serif;letter-spacing:.025em;background:linear-gradient(90deg,#76e9ff,#fff,#b8a4ff);-webkit-background-clip:text;color:transparent;max-width:290px}
      #maya-agent-hub-portal-card .mah-sub{font:500 13px/1.4 Segoe UI,Arial,sans-serif;color:#9cb7d7}
      #maya-agent-hub-portal-card .mah-open{margin-top:auto;padding-top:18px;font:800 12px/1 Segoe UI,Arial,sans-serif;letter-spacing:.12em;color:#9cecff}
      #maya-agent-hub-portal-card.mah-floating{position:fixed;right:18px;bottom:18px;width:310px;min-height:175px;z-index:999999;box-shadow:0 20px 70px rgba(0,0,0,.65)}
      @media(max-width:700px){#maya-agent-hub-portal-card.mah-floating{right:10px;bottom:10px;width:calc(100% - 20px);min-height:150px}}
    `;
    document.head.appendChild(style);

    if (grid) grid.appendChild(a);
    else { a.classList.add('mah-floating'); document.body.appendChild(a); }
    return true;
  }

  let tries = 0;
  const timer = setInterval(() => {
    tries++;
    if (addCard() || tries > 20) clearInterval(timer);
  }, 500);
})();
