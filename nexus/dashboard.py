"""The monitoring surface: a localhost page and a one-line status.

This module is deliberately *not* reachable from `nexus.server`. The agent
never receives dashboard content, so the dashboard costs zero context
tokens — it reads the same files on disk that the agent's tools write.
A test asserts that separation rather than trusting it.

Local only: the server binds to 127.0.0.1 and nothing is published anywhere.
"""
from __future__ import annotations

import html
import json
import subprocess
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import gate as gate_mod, tokens as tokens_mod
from .graph import GraphMissing, load as load_graph
from .store import Store


def state(root: Path) -> dict:
    root = Path(root).resolve()
    store = Store(root)

    try:
        stats = store.stats()
    except Exception as e:
        stats = {"live": 0, "superseded": 0, "by_type": {}, "error": str(e)}

    graph: dict = {"available": False, "detail": "not built"}
    try:
        g = load_graph(root)
        s = g.staleness(root, extensions={".py", ".js", ".ts", ".go", ".rs"})
        graph = {"available": True, "nodes": len(g.nodes), "links": len(g.links),
                 "fresh": not s.is_stale, "detail": s.summary(),
                 "changed": s.changed[:10], "unindexed": s.unindexed[:10],
                 "deleted": s.deleted[:10]}
    except GraphMissing as e:
        graph["detail"] = str(e).split(".")[0]
    except Exception as e:
        graph["detail"] = f"unreadable: {e}"

    plan = gate_mod.load_latest_plan(root)
    task = {"plan_id": None, "targets": [], "gear": None, "roles": [], "blocked": False}
    if plan:
        task = {"plan_id": plan.id, "targets": plan.targets, "gear": plan.gear,
                "roles": [r["name"] for r in plan.roles], "blocked": plan.blocked,
                "risks": plan.risks}

    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root,
                              capture_output=True, text=True, timeout=10)
        commit = head.stdout.strip() if head.returncode == 0 else ""
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                               capture_output=True, text=True, timeout=10)
        dirty_count = len([l for l in dirty.stdout.splitlines() if l.strip()])
    except (OSError, subprocess.SubprocessError):
        commit, dirty_count = "", 0

    return {"root": str(root), "memory": stats, "graph": graph, "task": task,
            "tokens": tokens_mod.totals(root), "git": {"head": commit, "dirty": dirty_count}}


def compact_line(s: dict) -> str:
    """One line, for a terminal status line. No colour codes — hosts add their own."""
    mem = s["memory"]["live"]
    g = s["graph"]
    graph_bit = ("graph —" if not g["available"]
                 else f"graph {g['nodes']}{'' if g['fresh'] else ' STALE'}")
    t = s["tokens"]
    tok_bit = (f"saved~{t['saved_estimated']:,}" if t["packs"] else "saved~0")
    task = s["task"]
    task_bit = (f"{task['gear']}:{','.join(task['roles'][:3])}" if task["plan_id"] else "no plan")
    if task.get("blocked"):
        task_bit += " BLOCKED"
    dirty = s["git"]["dirty"]
    return f"nexus · mem {mem} · {graph_bit} · {task_bit} · {tok_bit} · {dirty} dirty"


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS</title>
<style>
:root{--bg:#0f1115;--card:#171a21;--line:#262b36;--fg:#e6e9ef;--dim:#8b93a7;
--ok:#4ade80;--warn:#fbbf24;--bad:#f87171;--accent:#60a5fa}
@media (prefers-color-scheme:light){:root{--bg:#f6f7f9;--card:#fff;--line:#e3e6ec;
--fg:#161920;--dim:#5d6578;--ok:#15803d;--warn:#a16207;--bad:#b91c1c;--accent:#1d4ed8}}
*{box-sizing:border-box}
body{margin:0;padding:24px 16px;background:var(--bg);color:var(--fg);
font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}
.wrap{max-width:980px;margin:0 auto}
h1{font-size:15px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim);
margin:0 0 4px;font-weight:600}
.root{color:var(--dim);font-size:12px;margin-bottom:20px;word-break:break-all}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.k{color:var(--dim);font-size:11px;letter-spacing:.1em;text-transform:uppercase;margin-bottom:8px}
.v{font-size:26px;font-weight:600;line-height:1.1}
.sub{color:var(--dim);font-size:12px;margin-top:6px;word-break:break-word}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}.accent{color:var(--accent)}
table{width:100%;border-collapse:collapse;margin-top:4px}
td{padding:3px 0;font-size:12px;vertical-align:top}
td.l{color:var(--dim);width:42%}
.full{grid-column:1/-1}
ul{margin:6px 0 0;padding-left:18px;color:var(--dim);font-size:12px}
footer{color:var(--dim);font-size:11px;margin-top:20px;text-align:center}
</style></head><body><div class="wrap">
<h1>NEXUS</h1><div class="root" id="root">…</div>
<div class="grid" id="grid"></div>
<footer id="foot">reads <code>.nexus/</code> on disk · costs the agent zero tokens · 127.0.0.1 only</footer>
</div>
<script>
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function card(k, v, sub, cls){return `<div class="card"><div class="k">${esc(k)}</div>
<div class="v ${cls||''}">${esc(v)}</div><div class="sub">${sub||''}</div></div>`}
function render(s){
  document.getElementById('root').textContent = s.root;
  const g = s.graph, t = s.tokens, task = s.task, m = s.memory;
  const byType = Object.entries(m.by_type||{}).map(([k,v])=>`${esc(k)} ${v}`).join(' · ') || 'empty';
  const graphCls = !g.available ? 'dim' : (g.fresh ? 'ok' : 'warn');
  const taskCls = task.blocked ? 'bad' : (task.gear === 'full' ? 'warn' : 'ok');
  const rows = [
    card('Memory', m.live, byType + ` · ${m.superseded} superseded`),
    card('Knowledge graph', g.available ? g.nodes + ' nodes' : 'none', esc(g.detail), graphCls),
    card('Current task', task.plan_id ? task.gear : 'no plan',
         task.plan_id ? esc((task.targets||[]).join(', ')) + '<br>roles: ' + esc((task.roles||[]).join(', ')) : 'run <code>nexus plan &lt;file&gt;</code>', taskCls),
    card('Working tree', s.git.dirty + ' dirty', 'HEAD ' + esc(s.git.head || 'n/a')),
    `<div class="card full"><div class="k">Tokens — ${esc(t.packs)} pack(s)</div><table>
      <tr><td class="l">actual (measured)</td><td>${t.actual_measured.toLocaleString()}</td></tr>
      <tr><td class="l">baseline (measured)</td><td>${t.baseline_measured.toLocaleString()}</td></tr>
      <tr><td class="l">saved (estimated)</td><td class="accent">${t.saved_estimated.toLocaleString()}</td></tr>
      <tr><td class="l">tokenizer</td><td>${esc(t.tokenizer)}</td></tr></table>
      <div class="sub">“saved” is an estimate: the baseline is a counterfactual that was never run.</div></div>`
  ];
  const stale = [].concat((g.changed||[]).map(f=>'changed: '+f), (g.unindexed||[]).map(f=>'never indexed: '+f), (g.deleted||[]).map(f=>'deleted: '+f));
  if (stale.length) rows.push(`<div class="card full"><div class="k">Graph drift</div>
    <ul>${stale.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>
    <div class="sub">rebuild with <code>/graphify . --update</code> in your agent</div></div>`);
  if ((task.risks||[]).length) rows.push(`<div class="card full"><div class="k">Risks on the current plan</div>
    <ul>${task.risks.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>`);
  document.getElementById('grid').innerHTML = rows.join('');
}
async function tick(){
  try{ render(await (await fetch('/api/state',{cache:'no-store'})).json());
       document.getElementById('foot').textContent =
         'updated ' + new Date().toLocaleTimeString() + ' · reads .nexus/ on disk · costs the agent zero tokens · 127.0.0.1 only';
  }catch(e){ document.getElementById('foot').textContent = 'server stopped'; }
}
tick(); setInterval(tick, 3000);
</script></body></html>
"""


def _handler(root: Path):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: bytes, ctype: str, code: int = 200):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/api/state"):
                self._send(json.dumps(state(root)).encode(), "application/json")
            elif self.path in ("/", "/index.html"):
                self._send(PAGE.encode(), "text/html; charset=utf-8")
            else:
                self._send(b"not found", "text/plain", 404)

        def log_message(self, *a):  # keep the terminal clean
            pass
    return Handler


def serve(root: Path, port: int = 7373, open_browser: bool = True) -> None:
    root = Path(root).resolve()
    server = ThreadingHTTPServer(("127.0.0.1", port), _handler(root))
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"NEXUS dashboard at {url}  (local only — Ctrl-C to stop)")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()


def render_static(root: Path, out: Path) -> Path:
    """A snapshot page with the state baked in — no server, still local-only."""
    page = PAGE.replace(
        "tick(); setInterval(tick, 3000);",
        f"render({json.dumps(state(root))});\n"
        "document.getElementById('foot').textContent = "
        "'static snapshot · reads .nexus/ on disk · costs the agent zero tokens';")
    out = Path(out)
    out.write_text(page, encoding="utf-8")
    return out
