from __future__ import annotations

import hashlib
import html
import json
import os
import platform
import re
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
import traceback
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
DB_PATH = ROOT / "agent_hub.sqlite3"
STATIC = ROOT / "static"
_LOCK = threading.RLock()
VERSION = "2.1"


def tailscale_ipv4():
    """Return this host's Tailscale IPv4 if the CLI is available."""
    candidates = ["tailscale", "tailscale.exe", r"C:\Program Files\Tailscale\tailscale.exe"]
    for exe in candidates:
        try:
            cp = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=3, check=False)
            if cp.returncode == 0:
                for line in cp.stdout.splitlines():
                    ip = line.strip()
                    if re.fullmatch(r"100\.\d+\.\d+\.\d+", ip):
                        return ip
        except Exception:
            pass
    return None


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def db_conn():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            summary TEXT,
            payload TEXT
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS ix_runs_agent_id ON runs(agent, id DESC)")
        c.commit()


def log_run(agent, started, status, summary, payload):
    with db_conn() as c:
        c.execute(
            "INSERT INTO runs(agent, started_at, finished_at, status, summary, payload) VALUES (?,?,?,?,?,?)",
            (agent, started, now_iso(), status, summary, json.dumps(payload, ensure_ascii=False)),
        )
        c.commit()


def last_run(agent):
    with db_conn() as c:
        row = c.execute("SELECT * FROM runs WHERE agent=? ORDER BY id DESC LIMIT 1", (agent,)).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["payload"] = json.loads(d.get("payload") or "{}")
    except Exception:
        d["payload"] = {"raw": d.get("payload")}
    return d


def recent_runs(limit=50):
    with db_conn() as c:
        rows = c.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d.get("payload") or "{}")
        except Exception:
            pass
        out.append(d)
    return out


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self._href = None
        self._cls = ""
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            d = dict(attrs)
            self._href = d.get("href")
            self._cls = d.get("class", "")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            text = re.sub(r"\s+", " ", "".join(self._text)).strip()
            if text:
                self.links.append({"href": self._href, "text": html.unescape(text), "class": self._cls})
            self._href = None
            self._text = []
            self._cls = ""


def fetch(url, timeout=15):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "sk-SK,sk;q=0.9,en;q=0.7",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8", errors="replace")


def unwrap_ddg(url):
    if not url:
        return url
    if url.startswith("//"):
        url = "https:" + url
    try:
        p = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(p.query)
        if "uddg" in qs:
            return qs["uddg"][0]
    except Exception:
        pass
    return url


def _clean_result(title, url, provider):
    title = re.sub(r"\s+", " ", html.unescape(title or "")).strip()
    url = html.unescape(url or "").strip()
    if not title or not url.startswith("http"):
        return None
    return {"title": title[:240], "url": url, "provider": provider}


def search_bing_rss(query, max_results=8):
    # Bing exposes a lightweight RSS representation and is considerably less
    # brittle than scraping a modern JavaScript search page.
    url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query, "format": "rss"})
    raw = fetch(url, timeout=12)
    root = ET.fromstring(raw)
    out = []
    for item in root.findall(".//item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        r = _clean_result(title, link, "bing-rss")
        if r:
            out.append(r)
        if len(out) >= max_results:
            break
    if not out:
        raise RuntimeError("Bing RSS returned no results")
    return out


def search_ddg_html(query, max_results=8):
    endpoints = [
        "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query}),
        "https://lite.duckduckgo.com/lite/?" + urllib.parse.urlencode({"q": query}),
    ]
    last_error = None
    for endpoint in endpoints:
        try:
            raw = fetch(endpoint, timeout=12)
            p = LinkParser(); p.feed(raw)
            out, seen = [], set()
            for item in p.links:
                href = unwrap_ddg(item["href"])
                cls = item.get("class", "")
                # HTML and Lite have slightly different markup.
                looks_result = ("result__a" in cls) or ("duckduckgo.com/l/" in (item["href"] or "")) or ("nofollow" in cls)
                if not looks_result and "duckduckgo.com" in (href or ""):
                    continue
                r = _clean_result(item["text"], href, "duckduckgo")
                if not r or r["url"] in seen:
                    continue
                seen.add(r["url"]); out.append(r)
                if len(out) >= max_results:
                    break
            if out:
                return out
            last_error = RuntimeError("DuckDuckGo returned no result links")
        except Exception as e:
            last_error = e
    raise last_error or RuntimeError("DuckDuckGo search failed")


def web_search(query, max_results=8):
    """Search with provider failover. A query only fails if all providers fail."""
    errors = []
    providers = (search_bing_rss, search_ddg_html)
    merged, seen = [], set()
    for provider in providers:
        try:
            rows = provider(query, max_results)
            for r in rows:
                if r["url"] in seen:
                    continue
                seen.add(r["url"]); merged.append(r)
                if len(merged) >= max_results:
                    return merged
        except Exception as e:
            errors.append(f"{provider.__name__}: {e}")
    if merged:
        return merged
    raise RuntimeError(" | ".join(errors) if errors else "No search provider returned results")


def score_text(text, positive, negative=None):
    t = text.lower()
    score = 50
    hits = []
    for w, weight in positive.items():
        if w.lower() in t:
            score += weight
            hits.append(w)
    for w, weight in (negative or {}).items():
        if w.lower() in t:
            score -= weight
            hits.append("-" + w)
    return max(0, min(100, score)), hits


class Agent:
    key = "base"
    title = "Base Agent"

    def run(self, reason="manual", **kwargs):
        started = now_iso()
        try:
            payload = self.execute(reason=reason, **kwargs)
            summary = payload.get("summary", "OK")
            log_run(self.key, started, "ok", summary, payload)
            return {"ok": True, "agent": self.key, **payload}
        except Exception as e:
            payload = {"error": str(e), "trace": traceback.format_exc(limit=5)}
            log_run(self.key, started, "error", str(e), payload)
            return {"ok": False, "agent": self.key, **payload}

    def execute(self, **kwargs):
        raise NotImplementedError


class BusinessHunter(Agent):
    key = "business_hunter"
    title = "Business Hunter"

    def execute(self, **kwargs):
        cfg = load_config()["agents"][self.key]
        results, errors = [], []
        positive = cfg["positive_keywords"]
        negative = cfg.get("negative_keywords", {})
        for q in cfg["queries"]:
            try:
                for r in web_search(q, cfg.get("results_per_query", 6)):
                    s, hits = score_text(r["title"] + " " + r["url"], positive, negative)
                    results.append({**r, "query": q, "score": s, "hits": hits})
            except Exception as e:
                errors.append({"query": q, "error": str(e)})
        dedup = {r["url"]: r for r in sorted(results, key=lambda x: x["score"], reverse=True)}
        top = list(dedup.values())[:15]
        return {"summary": f"{len(top)} business signals, {len(errors)} source errors", "items": top, "errors": errors}


class JobHunter(Agent):
    key = "job_hunter"
    title = "Job Hunter"

    def execute(self, **kwargs):
        cfg = load_config()["agents"][self.key]
        results, errors = [], []
        for q in cfg["queries"]:
            try:
                for r in web_search(q, cfg.get("results_per_query", 8)):
                    s, hits = score_text(r["title"] + " " + r["url"], cfg["positive_keywords"], cfg.get("negative_keywords", {}))
                    results.append({**r, "query": q, "match": s, "hits": hits})
            except Exception as e:
                errors.append({"query": q, "error": str(e)})
        dedup = {r["url"]: r for r in sorted(results, key=lambda x: x["match"], reverse=True)}
        top = list(dedup.values())[:20]
        return {"summary": f"{len(top)} job matches, {len(errors)} source errors", "items": top, "errors": errors}


class ServerCaretaker(Agent):
    key = "server_caretaker"
    title = "Server Caretaker"

    @staticmethod
    def tcp_check(host, port, timeout=1.5):
        started = time.perf_counter()
        try:
            with socket.create_connection((host, int(port)), timeout=timeout):
                return True, round((time.perf_counter() - started) * 1000)
        except OSError:
            return False, None

    def execute(self, **kwargs):
        cfg = load_config()["agents"][self.key]
        services, down = [], []
        for svc in cfg["services"]:
            ok, latency = self.tcp_check(svc.get("host", "127.0.0.1"), svc["port"])
            row = {"name": svc["name"], "port": svc["port"], "ok": ok, "latency_ms": latency, "restart_attempted": False}
            if not ok:
                down.append(svc["name"])
                cmd = svc.get("restart_command", "").strip()
                if cfg.get("auto_restart") and cmd:
                    try:
                        subprocess.Popen(cmd, shell=True, cwd=svc.get("cwd") or None)
                        row["restart_attempted"] = True
                    except Exception as e:
                        row["restart_error"] = str(e)
            services.append(row)
        return {"summary": "All services healthy" if not down else f"DOWN: {', '.join(down)}", "services": services, "down": down}


class NetworkWatcher(Agent):
    key = "network_watcher"
    title = "Nomadic Network Watcher"

    def execute(self, **kwargs):
        total, used, free = shutil.disk_usage(ROOT.anchor or "/")
        host = socket.gethostname()
        ips = []
        try:
            ips = sorted(set(socket.gethostbyname_ex(host)[2]))
        except Exception:
            pass
        ts_ip = tailscale_ipv4()
        payload = {
            "hostname": host,
            "platform": platform.platform(),
            "python": platform.python_version(),
            "ips": ips,
            "tailscale_ip": ts_ip,
            "agent_hub_urls": {
                "local": "http://localhost:8065",
                "tailscale": f"http://{ts_ip}:8065" if ts_ip else None,
            },
            "disk": {"total_gb": round(total/2**30,1), "used_gb": round(used/2**30,1), "free_gb": round(free/2**30,1), "used_pct": round(used/total*100,1)},
        }
        ts_note = f", Tailscale {ts_ip}" if ts_ip else ", Tailscale IP not detected"
        return {"summary": f"{host}: disk {payload['disk']['used_pct']}% used{ts_note}", **payload}


class LandHunter(Agent):
    key = "land_hunter"
    title = "MiniFarma Land Hunter"

    def execute(self, **kwargs):
        cfg = load_config()["agents"][self.key]
        items, errors = [], []
        for q in cfg["queries"]:
            try:
                for r in web_search(q, cfg.get("results_per_query", 8)):
                    s, hits = score_text(r["title"] + " " + r["url"], cfg["positive_keywords"], cfg.get("negative_keywords", {}))
                    items.append({**r, "query": q, "score": s, "hits": hits})
            except Exception as e:
                errors.append({"query": q, "error": str(e)})
        dedup = {r["url"]: r for r in sorted(items, key=lambda x: x["score"], reverse=True)}
        top = list(dedup.values())[:20]
        return {"summary": f"{len(top)} land leads", "items": top, "errors": errors}


class PhotoLibrarian(Agent):
    key = "photo_librarian"
    title = "Photo Librarian"

    def execute(self, **kwargs):
        cfg = load_config()["agents"][self.key]
        exts = set(x.lower() for x in cfg.get("extensions", [".jpg", ".jpeg", ".png", ".webp", ".dng"]))
        folders = []
        total_files = total_bytes = 0
        for raw in cfg["folders"]:
            p = Path(raw)
            count = size = 0
            if p.exists():
                for root, _, files in os.walk(p):
                    for name in files:
                        if Path(name).suffix.lower() in exts:
                            count += 1
                            try:
                                size += (Path(root)/name).stat().st_size
                            except OSError:
                                pass
            folders.append({"path": raw, "exists": p.exists(), "photos": count, "gb": round(size/2**30, 2)})
            total_files += count; total_bytes += size
        return {"summary": f"{total_files} media files indexed", "folders": folders, "photos": total_files, "gb": round(total_bytes/2**30, 2)}


class NomadicContentAgent(Agent):
    key = "nomadic_content"
    title = "Nomadic Tide Content Agent"

    def execute(self, **kwargs):
        last = last_run("photo_librarian")
        payload = {"photo_index_available": bool(last), "next_actions": [
            "Select newest high-quality media batch",
            "Create web gallery queue by year/location",
            "Prepare caption/reel drafts after content source is connected"
        ]}
        return {"summary": "Content pipeline ready; publishing remains approval-only", **payload}


class ResearchAgent(Agent):
    key = "research_agent"
    title = "Research Lab"

    def execute(self, **kwargs):
        query = (kwargs.get("query") or "AI agents small business automation Slovakia").strip()
        items = web_search(query, 10)
        return {"summary": f"{len(items)} research sources for: {query[:80]}", "query": query, "items": items}


class WTIIntegration(Agent):
    key = "wti_integration"
    title = "Maya's Oil Agent Bridge"

    def execute(self, **kwargs):
        cfg = load_config()["agents"][self.key]
        url = cfg.get("existing_agent_url", "").strip()
        if not url:
            return {"summary": "Bridge ready; set existing_agent_url in config.json", "connected": False}
        try:
            raw = fetch(url, timeout=5)
            return {"summary": "Existing Oil Agent reachable", "connected": True, "url": url, "preview": re.sub(r"\s+", " ", raw)[:300]}
        except Exception as e:
            return {"summary": f"Oil Agent bridge offline: {e}", "connected": False, "url": url}


class MayaCoordinator(Agent):
    key = "maya_coordinator"
    title = "Maya Coordinator"

    def execute(self, **kwargs):
        keys = ["business_hunter", "job_hunter", "server_caretaker", "network_watcher", "land_hunter", "photo_librarian", "nomadic_content", "wti_integration"]
        state = []
        alerts = []
        for k in keys:
            lr = last_run(k)
            if lr:
                row = {"agent": k, "status": lr["status"], "summary": lr.get("summary"), "finished_at": lr.get("finished_at")}
                state.append(row)
                if lr["status"] != "ok" or (lr.get("summary") or "").startswith("DOWN:"):
                    alerts.append(row)
            else:
                state.append({"agent": k, "status": "never_run", "summary": "No run yet"})
        return {"summary": f"{len(state)} agents summarized, {len(alerts)} alerts", "agents": state, "alerts": alerts}


AGENTS = {
    a.key: a() for a in [BusinessHunter, JobHunter, ServerCaretaker, NetworkWatcher, LandHunter,
                         PhotoLibrarian, NomadicContentAgent, ResearchAgent, WTIIntegration, MayaCoordinator]
}

RUNNING = set()


def run_agent(key, reason="manual", **kwargs):
    if key not in AGENTS:
        return {"ok": False, "error": "unknown agent"}
    with _LOCK:
        if key in RUNNING:
            return {"ok": False, "agent": key, "error": "already running"}
        RUNNING.add(key)
    try:
        return AGENTS[key].run(reason=reason, **kwargs)
    finally:
        with _LOCK:
            RUNNING.discard(key)


def run_async(key, reason="manual", **kwargs):
    threading.Thread(target=run_agent, args=(key, reason), kwargs=kwargs, daemon=True).start()


def scheduler_loop():
    last_times = {}
    while True:
        try:
            cfg = load_config()
            for key, acfg in cfg.get("agents", {}).items():
                if key not in AGENTS or not acfg.get("enabled", False):
                    continue
                interval = max(1, int(acfg.get("interval_minutes", 60))) * 60
                due = time.time() - last_times.get(key, 0) >= interval
                if due and key not in RUNNING:
                    last_times[key] = time.time()
                    run_async(key, "scheduled")
        except Exception as e:
            print("scheduler error:", e)
        time.sleep(30)


class Handler(BaseHTTPRequestHandler):
    server_version = "MayaAgentHub/2.0"

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def send_json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_file(self, path, content_type):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/status":
            cfg = load_config()
            items = []
            for key, agent in AGENTS.items():
                acfg = cfg.get("agents", {}).get(key, {})
                lr = last_run(key)
                items.append({"key": key, "title": agent.title, "enabled": acfg.get("enabled", False), "interval_minutes": acfg.get("interval_minutes"), "running": key in RUNNING, "last": lr})
            ts_ip = tailscale_ipv4()
            return self.send_json({
                "version": VERSION,
                "time": now_iso(),
                "port": cfg["server"]["port"],
                "tailscale_ip": ts_ip,
                "access_urls": {
                    "local": f"http://localhost:{cfg['server']['port']}",
                    "tailscale": f"http://{ts_ip}:{cfg['server']['port']}" if ts_ip else None,
                },
                "agents": items
            })
        if u.path == "/api/runs":
            qs = urllib.parse.parse_qs(u.query)
            limit = min(200, max(1, int(qs.get("limit", [50])[0])))
            return self.send_json({"runs": recent_runs(limit)})
        if u.path == "/api/config":
            cfg = load_config()
            safe = json.loads(json.dumps(cfg))
            return self.send_json(safe)
        if u.path == "/" or u.path == "/index.html":
            return self.serve_file(STATIC / "index.html", "text/html; charset=utf-8")
        if u.path == "/app.js":
            return self.serve_file(STATIC / "app.js", "application/javascript; charset=utf-8")
        if u.path == "/styles.css":
            return self.serve_file(STATIC / "styles.css", "text/css; charset=utf-8")
        self.send_error(404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(n) if n else b"{}"
        try:
            data = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            data = {}
        if u.path.startswith("/api/run/"):
            key = u.path.split("/")[-1]
            if key == "all":
                for k in AGENTS:
                    if k != "maya_coordinator":
                        run_async(k, "manual_all")
                return self.send_json({"ok": True, "message": "All agents queued"}, 202)
            if key not in AGENTS:
                return self.send_json({"ok": False, "error": "unknown agent"}, 404)
            run_async(key, "manual", **data)
            return self.send_json({"ok": True, "message": f"{key} queued"}, 202)
        self.send_error(404)


def main():
    init_db()
    cfg = load_config()
    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()
    host = cfg["server"].get("host", "0.0.0.0")
    port = int(cfg["server"].get("port", 8065))
    print(f"MAYA AGENT HUB listening on http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
