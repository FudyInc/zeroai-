#!/usr/bin/env python3
"""Local web dashboard + landing for ZERO — something to SHOW when selling.

Reads the same `crm.json` the CLI writes and renders it as a clean HTML dashboard
in the browser. Stdlib only, runs locally (deploy later if it earns its keep). It
only DISPLAYS what the pipeline already produced — no new data, no external service.

    python3 webapp.py                      # serve at http://localhost:8000
    python3 webapp.py --crm crm.json --port 8000
"""
from __future__ import annotations

import argparse
import html
from http.server import BaseHTTPRequestHandler, HTTPServer

from zero.config import AVG_DEAL_VALUE_USD, CRM_OPEN_STAGES, CRM_STAGES
from zero.crm import CRM

_LABEL = {
    "new": "Nuevos", "qualified": "Calificados", "disqualified": "Descartados",
    "contacted": "Contactados", "nurturing": "En seguimiento", "replied": "Respondieron",
    "meeting": "Reunión", "won": "Ganados", "lost": "Perdidos",
}
_COLOR = {
    "new": "#64748b", "qualified": "#0284c7", "disqualified": "#e11d48",
    "contacted": "#d97706", "nurturing": "#db2777", "replied": "#2563eb",
    "meeting": "#059669", "won": "#16a34a", "lost": "#94a3b8",
}

_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
/* design tokens from the Figma export (shadcn/ui) */
:root{--bg:#ffffff;--panel:#ffffff;--line:rgba(0,0,0,.1);--ink:#242424;--strong:#030213;
      --mut:#717182;--soft:#ececf0;--input:#f3f3f5;--accent:#6366f1;--r:10px}
body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Inter,Helvetica,Arial,sans-serif;
     background:var(--bg);color:var(--ink);min-height:100vh}
.topbar{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:16px;
     padding:16px 32px;background:rgba(255,255,255,.85);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.brand{font-size:22px;font-weight:800;letter-spacing:1px;
     background:linear-gradient(90deg,#6366f1,#a855f7);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.tag{color:var(--mut);font-size:14px}
.badge{margin-left:auto;font-size:11px;color:#6d28d9;border:1px solid #ddd6fe;background:#f5f3ff;
     padding:4px 10px;border-radius:999px;letter-spacing:.5px;text-transform:uppercase}
.lead{padding:30px 32px 6px}
.lead h1{font-size:30px;font-weight:800;letter-spacing:.3px;color:var(--strong)}
.lead p{color:var(--mut);font-size:16px;margin-top:6px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;padding:22px 32px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:16px 18px;
     box-shadow:0 1px 2px rgba(16,24,40,.04)}
.kpi .v{color:var(--strong)}
.kpi .v{font-size:26px;font-weight:800}
.kpi .l{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.6px;margin-top:4px}
.wrap{padding:8px 32px 40px}
.client{margin-bottom:34px}
.client h2{font-size:13px;color:#334155;text-transform:uppercase;letter-spacing:1.2px;
     margin-bottom:14px;padding-left:10px;border-left:3px solid var(--accent)}
.board{display:flex;gap:14px;overflow-x:auto;padding-bottom:10px}
.col{min-width:248px;flex:0 0 248px}
.col h3{font-size:11px;letter-spacing:.6px;text-transform:uppercase;margin-bottom:12px;
     display:flex;align-items:center;gap:7px}
.dot{width:8px;height:8px;border-radius:50%}
.pill{margin-left:auto;background:var(--soft);color:var(--mut);border-radius:999px;padding:1px 9px;font-size:11px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:12px 14px;margin-bottom:10px;
     box-shadow:0 1px 2px rgba(16,24,40,.04);transition:transform .12s,box-shadow .12s,border-color .12s}
.card:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(16,24,40,.08);border-color:#d6dae3}
.card .co{font-weight:700;color:var(--strong);display:flex;justify-content:space-between;gap:8px}
.card .sc{font-weight:800}
.card .meta{color:var(--mut);font-size:12.5px;margin-top:4px}
.empty{color:var(--mut);padding:60px 0;font-size:15px;line-height:1.7}
.empty code{background:var(--input);border:1px solid var(--line);padding:3px 8px;border-radius:6px;color:#4f46e5}
.foot{color:#9aa3b2;font-size:12px;padding:0 32px 34px}
"""


def _sc_color(score):
    if score is None:
        return "#94a3b8"
    return "#16a34a" if score >= 80 else "#d97706" if score >= 70 else "#dc2626"


def _card(rec: dict) -> str:
    score = rec.get("score")
    sc = f'<span class="sc" style="color:{_sc_color(score)}">{score if score is not None else "—"}</span>'
    contact = rec.get("email") or rec.get("phone") or "—"
    return (
        f'<div class="card"><div class="co"><span>{html.escape(str(rec.get("company") or "—"))}</span>{sc}</div>'
        f'<div class="meta">{html.escape(str(rec.get("role") or "—"))}</div>'
        f'<div class="meta">{html.escape(str(contact))}</div></div>'
    )


def _client_board(crm: CRM, client: str) -> str:
    cols = []
    for stage in CRM_STAGES:
        leads = crm.list(client, stage)
        if not leads:
            continue
        color = _COLOR.get(stage, "#94a3b8")
        cards = "".join(_card(r) for r in leads)
        cols.append(
            f'<div class="col"><h3 style="color:{color}"><span class="dot" style="background:{color}"></span>'
            f'{_LABEL.get(stage, stage)}<span class="pill">{len(leads)}</span></h3>{cards}</div>'
        )
    return f'<div class="client"><h2>{html.escape(client)}</h2><div class="board">{"".join(cols)}</div></div>'


def _kpis(crm: CRM) -> str:
    leads = list(crm.leads.values())
    total = len(leads)
    in_pipe = sum(1 for r in leads if r.get("stage") in CRM_OPEN_STAGES)
    won = sum(1 for r in leads if r.get("stage") == "won")
    pipeline = won * AVG_DEAL_VALUE_USD
    cards = [
        ("Leads totales", str(total)),
        ("En pipeline", str(in_pipe)),
        ("Ganados", str(won)),
        ("Pipeline ganado", f"${pipeline:,.0f}"),
    ]
    return '<div class="kpis">' + "".join(
        f'<div class="kpi"><div class="v">{v}</div><div class="l">{l}</div></div>' for l, v in cards
    ) + "</div>"


def render_page(crm: CRM) -> str:
    clients = sorted({r["client_id"] for r in crm.leads.values()})
    top = ('<div class="topbar"><div class="brand">ZERO</div>'
           '<div class="tag">Lead-gen B2B · panel de control</div>'
           '<div class="badge">local · demo</div></div>')
    lead = ('<div class="lead"><h1>Leads B2B calificados y confiables</h1>'
            '<p>Descubrimos, calificamos y preparamos tus prospectos. Solo entregamos lo que pasa el filtro: '
            'score ≥ 70, contacto verificado, primer mensaje listo.</p></div>')
    if not clients:
        body = ('<div class="wrap"><p class="empty">Aún no hay datos. Corré una pipeline y recargá:<br><br>'
                '<code>python3 main.py --client demo --tier GROWTH --query "fintech LATAM"</code></p></div>')
        return f"<!doctype html><html><head><meta charset='utf-8'><title>ZERO</title><style>{_CSS}</style></head><body>{top}{lead}{body}</body></html>"
    boards = "".join(_client_board(crm, c) for c in clients)
    foot = '<div class="foot">Vista local · datos de crm.json · solo muestra lo que el pipeline ya produjo.</div>'
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>ZERO · panel</title>"
            f"<style>{_CSS}</style></head><body>{top}{lead}{_kpis(crm)}"
            f'<div class="wrap">{boards}</div>{foot}</body></html>')


class Handler(BaseHTTPRequestHandler):
    crm_path = "crm.json"

    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self.send_response(404)
            self.end_headers()
            return
        body = render_page(CRM(self.crm_path)).encode("utf-8")   # reload so it's always fresh
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="ZERO local web dashboard")
    p.add_argument("--crm", default="crm.json", help="CRM store to display")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)

    Handler.crm_path = args.crm
    print(f"ZERO dashboard → http://localhost:{args.port}   (Ctrl+C para parar)")
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    main()
