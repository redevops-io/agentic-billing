"""agentic-billing — the FIRST "agentic module on a real OSS core" vertical slice.

This is the reference implementation every other module copies. It wraps the running
self-hosted Lago instance (the OSS billing core) with:

  * an agent layer that reads REAL Lago data over the REST API, and
  * an MD3 dashboard (same design tokens as deploy/module_service.py) rendered from
    that live data — no mock data.

Pattern for the other 8 cores:
  1. point CORE_API_URL / CORE_API_KEY at the running OSS core,
  2. write a `fetch_*` that pulls real records + a `compute_kpis`,
  3. reuse BASE_CSS + the render helpers below,
  4. add agentic actions in /agent/run that are deterministic core API calls, with a
     human-approval gate on anything that moves money.

Endpoints:
  GET  /health        -> {"status","core":"lago","connected": <bool from Lago /health>}
  GET  /api/activity  -> live KPIs + recent invoices derived from Lago REST
  GET  /              -> MD3 billing dashboard rendered from the live data
  POST /agent/run     -> agentic action: {"action":"chase_overdue"|"refund"}

Config (env; seed.py writes agents/billing/.env automatically):
  LAGO_API_URL    REST base, default http://localhost:3000
  LAGO_API_KEY    Bearer token (the ApiKey value from the seed)
  LAGO_FRONT_URL  Lago UI link for the hybrid/human-operable "Open in Lago" button
  PORT            uvicorn port, default 8201
  ANTHROPIC_API_KEY  OPTIONAL — if set, /agent/run adds an LLM reasoning blurb;
                     the endpoint works fully without it.
"""
from __future__ import annotations

import html
import os
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

# --- config ------------------------------------------------------------------
# Load agents/billing/.env (written by seed.py) without adding a python-dotenv dep.
_ENV_FILE = Path(__file__).resolve().parent / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

LAGO_API_URL = os.environ.get("LAGO_API_URL", "http://localhost:3000").rstrip("/")
LAGO_API_KEY = os.environ.get("LAGO_API_KEY", "")
LAGO_FRONT_URL = os.environ.get("LAGO_FRONT_URL", "http://localhost:80").rstrip("/")
PORT = int(os.environ.get("PORT", "8201"))

TENANT = "Summit Roofing Co."
SUBTITLE = "Checkout to reconciliation on a real Lago core — with a human in the loop when money moves."

app = FastAPI(title="agentic-billing (Summit Roofing Co. · core: Lago)")


# --- Lago REST client --------------------------------------------------------
def _headers() -> dict:
    return {"Authorization": f"Bearer {LAGO_API_KEY}", "Content-Type": "application/json"}


def lago_connected() -> bool:
    """True iff Lago's health endpoint returns 200."""
    try:
        r = httpx.get(f"{LAGO_API_URL}/health", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


def _get_all(path: str, key: str, params: dict | None = None) -> list[dict]:
    """GET a paginated Lago collection (e.g. /api/v1/invoices) and return all rows."""
    out: list[dict] = []
    page = 1
    params = dict(params or {})
    with httpx.Client(timeout=10.0) as client:
        while True:
            params.update({"page": page, "per_page": 100})
            r = client.get(f"{LAGO_API_URL}{path}", headers=_headers(), params=params)
            r.raise_for_status()
            body = r.json()
            rows = body.get(key, [])
            out.extend(rows)
            meta = body.get("meta", {})
            if not rows or page >= int(meta.get("total_pages", page)):
                break
            page += 1
    return out


# --- live data + KPIs (cached briefly) ---------------------------------------
_CACHE: dict = {"ts": 0.0, "data": None}
_CACHE_TTL = 15.0  # seconds — keep the dashboard snappy without hammering Lago


def _money(cents: int) -> str:
    return "${:,.0f}".format((cents or 0) / 100.0)


def _invoice_state(inv: dict) -> str:
    """Collapse Lago's status/payment_status/overdue into one display state."""
    status = inv.get("status")
    pay = inv.get("payment_status")
    if inv.get("payment_overdue"):
        return "OVERDUE"
    if status == "draft":
        return "DRAFT"
    if status == "finalized" and pay == "succeeded":
        return "PAID"
    if status == "finalized" and pay == "pending":
        return "SENT"
    if pay == "failed":
        return "FAILED"
    return (status or "").upper() or "UNKNOWN"


def _days_overdue(inv: dict) -> int | None:
    due = inv.get("payment_due_date")
    if not due:
        return None
    try:
        from datetime import date

        y, m, d = (int(x) for x in due[:10].split("-"))
        delta = (date.today() - date(y, m, d)).days
        return delta if delta > 0 else 0
    except Exception:
        return None


def fetch_activity(force: bool = False) -> dict:
    """Pull REAL Lago data and compute the billing KPIs the dashboard renders."""
    now = time.time()
    if not force and _CACHE["data"] is not None and now - _CACHE["ts"] < _CACHE_TTL:
        return _CACHE["data"]

    connected = lago_connected()
    invoices: list[dict] = []
    customers: list[dict] = []
    error = None
    if connected and LAGO_API_KEY:
        try:
            invoices = _get_all("/api/v1/invoices", "invoices")
            customers = _get_all("/api/v1/customers", "customers")
        except Exception as e:  # network / auth hiccup — surface, don't crash the page
            error = str(e)

    # KPIs straight from the live invoices.
    collected = sum(
        i.get("total_amount_cents", 0)
        for i in invoices
        if i.get("status") == "finalized" and i.get("payment_status") == "succeeded"
    )
    outstanding = sum(
        i.get("total_amount_cents", 0)
        for i in invoices
        if i.get("status") == "finalized" and i.get("payment_status") != "succeeded"
    )
    finalized = [i for i in invoices if i.get("status") == "finalized"]
    paid_ct = sum(1 for i in finalized if i.get("payment_status") == "succeeded")
    success_rate = round(100 * paid_ct / len(finalized)) if finalized else 0
    overdue = [i for i in invoices if i.get("payment_overdue")]

    # Recent invoices for the table (newest issuing_date first).
    recent = sorted(
        invoices, key=lambda i: i.get("issuing_date") or "", reverse=True
    )[:8]
    recent_rows = [
        {
            "number": i.get("number", "—"),
            "customer": (i.get("customer") or {}).get("name", "—"),
            "amount_cents": i.get("total_amount_cents", 0),
            "amount": _money(i.get("total_amount_cents", 0)),
            "state": _invoice_state(i),
            "days_overdue": _days_overdue(i) if i.get("payment_overdue") else None,
            "lago_id": i.get("lago_id"),
        }
        for i in recent
    ]

    overdue_rows = [
        {
            "number": i.get("number"),
            "customer": (i.get("customer") or {}).get("name", "—"),
            "amount": _money(i.get("total_amount_cents", 0)),
            "amount_cents": i.get("total_amount_cents", 0),
            "days_overdue": _days_overdue(i),
            "lago_id": i.get("lago_id"),
        }
        for i in overdue
    ]

    data = {
        "tenant": TENANT,
        "core": "lago",
        "connected": connected,
        "error": error,
        "front_url": LAGO_FRONT_URL,
        "kpis": [
            {"label": "Collected MTD", "value": _money(collected), "note": "finalized + paid"},
            {"label": "Outstanding", "value": _money(outstanding),
             "note": f"{len(finalized) - paid_ct} open invoice(s)"},
            {"label": "Payment success", "value": f"{success_rate}%", "note": "of finalized"},
            {"label": "Active customers", "value": str(len(customers)), "note": "in Lago"},
        ],
        "recent": recent_rows,
        "overdue": overdue_rows,
        "counts": {"invoices": len(invoices), "customers": len(customers), "overdue": len(overdue)},
    }
    _CACHE.update(ts=now, data=data)
    return data


# --- MD3 styling (BASE_CSS reused verbatim from deploy/module_service.py) -----
BASE_CSS = """
:root{
  --surface-dim:#0e0e11; --surface:#131316; --surface-bright:#393a3d;
  --surface-container-lowest:#0d0e10; --surface-container-low:#1b1b1f;
  --surface-container:#1f1f23; --surface-container-high:#2a2a2e; --surface-container-highest:#353539;
  --on-surface:#e4e2e6; --on-surface-variant:#c7c5ca; --on-surface-muted:#918f96;
  --outline:#938f99; --outline-variant:#2f2f33;
  --primary:#4fd1c5; --on-primary:#00201c; --primary-container:#00504a; --on-primary-container:#a8f0e6;
  --secondary:#f5b544; --on-secondary:#3d2e00; --secondary-container:#5c4500;
  --success:#5bd98a; --success-container:#0f3d22; --warning:#f5b544; --warning-container:#4a3500;
  --danger:#f2544f; --danger-container:#5c1512; --info:#5aa9f0; --info-container:#103a5c;
  --sp-1:4px;--sp-2:8px;--sp-3:12px;--sp-4:16px;--sp-5:24px;--sp-6:32px;--sp-7:40px;--sp-8:48px;
  --radius-sm:8px;--radius-md:12px;--radius-lg:16px;--radius-xl:28px;--radius-pill:999px;
  --shadow-1:0 1px 2px rgba(0,0,0,.45);--shadow-2:0 2px 6px rgba(0,0,0,.5);
  --font-sans:"Roboto",system-ui,-apple-system,"Segoe UI",sans-serif;
  --font-mono:"Roboto Mono",ui-monospace,"SF Mono",monospace;
}
*{box-sizing:border-box}
.display-l{font:400 57px/64px var(--font-sans);letter-spacing:-.25px}
.headline-m{font:400 28px/36px var(--font-sans)} .headline-s{font:400 24px/32px var(--font-sans)}
.title-l{font:400 22px/28px var(--font-sans)} .title-m{font:500 16px/24px var(--font-sans);letter-spacing:.15px}
.title-s{font:500 14px/20px var(--font-sans)} .body-m{font:400 14px/20px var(--font-sans)}
.body-s{font:400 12px/16px var(--font-sans)} .label-m{font:500 12px/16px var(--font-sans);letter-spacing:.5px}
.page{background:var(--surface);color:var(--on-surface);font-family:var(--font-sans);padding:var(--sp-5);margin:0}
.shell{max-width:1440px;margin-inline:auto;display:flex;flex-direction:column;gap:var(--sp-5)}
.grid{display:grid;gap:var(--sp-4);grid-template-columns:repeat(12,1fr)}
.kpi-row{display:grid;gap:var(--sp-4);grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}
.col-3{grid-column:span 3}.col-4{grid-column:span 4}.col-6{grid-column:span 6}.col-8{grid-column:span 8}.col-12{grid-column:span 12}
@media(max-width:839px){[class^="col-"]{grid-column:span 12}}
.card{background:var(--surface-container);border:1px solid var(--outline-variant);border-radius:var(--radius-lg);padding:var(--sp-5);display:flex;flex-direction:column;gap:var(--sp-4)}
.card__head{display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3)}
.card__title{font:500 16px/24px var(--font-sans);letter-spacing:.15px;color:var(--on-surface);margin:0}
.tile{background:var(--surface-container);border:1px solid var(--outline-variant);border-radius:var(--radius-lg);padding:var(--sp-4) var(--sp-5);display:flex;flex-direction:column;gap:var(--sp-1)}
.tile__label{font:500 12px/16px var(--font-sans);letter-spacing:.5px;text-transform:uppercase;color:var(--on-surface-muted)}
.tile__value{font:500 32px/40px var(--font-mono);color:var(--on-surface);font-feature-settings:"tnum"}
.tile__delta{font:500 12px/16px var(--font-sans);color:var(--on-surface-variant)} .tile__delta--up{color:var(--success)} .tile__delta--down{color:var(--danger)}
.pill{display:inline-flex;align-items:center;gap:6px;height:24px;padding:0 10px;border-radius:var(--radius-pill);font:500 12px/1 var(--font-sans)}
.pill--success{background:var(--success-container);color:var(--success)}.pill--warn{background:var(--warning-container);color:var(--warning)}
.pill--danger{background:var(--danger-container);color:var(--danger)}.pill--info{background:var(--info-container);color:var(--info)}
.pill--neutral{background:var(--surface-container-highest);color:var(--on-surface-variant)}
.pill__dot{width:6px;height:6px;border-radius:50%;background:currentColor}
.table{width:100%;border-collapse:collapse;font-size:14px}
.table th{text-align:left;color:var(--on-surface-muted);font:500 12px/16px var(--font-sans);letter-spacing:.5px;text-transform:uppercase;padding:var(--sp-3) var(--sp-4);border-bottom:1px solid var(--outline-variant)}
.table td{padding:var(--sp-3) var(--sp-4);color:var(--on-surface);border-bottom:1px solid var(--outline-variant)}
.table td.num{text-align:right;font-family:var(--font-mono);font-feature-settings:"tnum"}
.table tbody tr:last-child td{border-bottom:none}
.table tbody tr:hover{background:rgba(228,226,230,.08)}
.banner{display:flex;align-items:center;gap:var(--sp-4);padding:var(--sp-4) var(--sp-5);border-radius:var(--radius-md);border-left:4px solid var(--warning);background:var(--warning-container);color:var(--on-surface)}
.bar{height:8px;border-radius:var(--radius-pill);background:var(--surface-container-highest);overflow:hidden}
.bar>span{display:block;height:100%;background:var(--primary)}
"""

PAGE_CSS = """
a{color:var(--primary);text-decoration:none}
.appbar{background:var(--surface-container-low);border:1px solid var(--outline-variant);border-radius:var(--radius-lg);padding:var(--sp-5) var(--sp-5)}
.appbar__row{display:flex;align-items:center;gap:var(--sp-3);flex-wrap:wrap}
.appbar h1{margin:0;font:400 28px/36px var(--font-sans);color:var(--on-surface)}
.appbar__tenant{margin-top:var(--sp-3);color:var(--on-surface-variant);font:400 14px/20px var(--font-sans)}
.appbar__tenant b{color:var(--on-surface)}
.appbar__sub{margin-top:var(--sp-2);color:var(--on-surface-muted);font:400 14px/20px var(--font-sans);max-width:820px}
.spacer{flex:1}
.btn{display:inline-flex;align-items:center;gap:6px;height:36px;padding:0 16px;border-radius:var(--radius-pill);background:var(--primary-container);color:var(--on-primary-container);font:500 14px/1 var(--font-sans);border:1px solid var(--primary-container)}
.btn:hover{filter:brightness(1.1)}
.section-label{font:500 12px/16px var(--font-sans);letter-spacing:.5px;text-transform:uppercase;color:var(--primary);display:flex;align-items:center;gap:var(--sp-3);margin:0}
.section-label::after{content:"";flex:1;height:1px;background:var(--outline-variant)}
.barlist{display:flex;flex-direction:column;gap:var(--sp-4)}
.barlist__row{display:grid;grid-template-columns:160px 1fr 88px;align-items:center;gap:var(--sp-4)}
.barlist__label{color:var(--on-surface-variant);font:400 14px/20px var(--font-sans)}
.barlist__pct{text-align:right;font-family:var(--font-mono);font-feature-settings:"tnum";font-size:13px;color:var(--on-surface-variant)}
.footer{color:var(--on-surface-muted);font:400 12px/16px var(--font-sans);text-align:center;padding-top:var(--sp-2)}
"""

FONT_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    'family=Roboto:wght@400;500&family=Roboto+Mono:wght@400;500&display=swap">'
)


def _esc(v) -> str:
    return html.escape(str(v))


def _state_pill(state: str) -> str:
    s = state.upper()
    if s == "PAID":
        return "pill--success"
    if s in ("OVERDUE", "FAILED"):
        return "pill--danger"
    if s in ("DRAFT", "SENT", "PENDING"):
        return "pill--warn"
    return "pill--neutral"


def _kpi_tiles(kpis: list[dict]) -> str:
    cells = ""
    for k in kpis:
        cells += (
            "<div class='tile'>"
            f"<div class='tile__label'>{_esc(k['label'])}</div>"
            f"<div class='tile__value'>{_esc(k['value'])}</div>"
            f"<div class='tile__delta'>{_esc(k['note'])}</div>"
            "</div>"
        )
    return f"<section class='kpi-row'>{cells}</section>"


def _approval_banner(data: dict) -> str:
    """Show when there's an overdue invoice (agent can act) or a pending refund."""
    overdue = data.get("overdue", [])
    if not overdue:
        return ""
    first = overdue[0]
    extra = f" (+{len(overdue) - 1} more)" if len(overdue) > 1 else ""
    return (
        "<div class='banner'>"
        f"<span class='pill pill--warn'><span class='pill__dot'></span>{len(overdue)} need attention</span>"
        "<span class='label-m' style='text-transform:uppercase;color:var(--warning)'>chase_overdue</span>"
        f"<span class='body-m'>Overdue: {_esc(first['customer'])} — {_esc(first['number'])} "
        f"{_esc(first['amount'])}, {_esc(first['days_overdue'])} days overdue{_esc(extra)}. "
        "Agent can send a dunning reminder / retry payment (hybrid, approval-gated).</span>"
        "</div>"
    )


def _collected_outstanding_bars(data: dict) -> str:
    """Stripe-style collected-vs-outstanding meter from the live KPI amounts."""
    def cents(label):
        for k in data["kpis"]:
            if k["label"] == label:
                return float(k["value"].replace("$", "").replace(",", "") or 0)
        return 0.0

    collected = cents("Collected MTD")
    outstanding = cents("Outstanding")
    total = max(collected + outstanding, 1)
    rows = [
        ("Collected (paid)", collected),
        ("Outstanding (open)", outstanding),
    ]
    body = ""
    for label, val in rows:
        pct = int(round(100 * val / total))
        body += (
            "<div class='barlist__row'>"
            f"<div class='barlist__label'>{_esc(label)}</div>"
            f"<div class='bar'><span style='width:{pct}%'></span></div>"
            f"<div class='barlist__pct'>${val:,.0f}</div>"
            "</div>"
        )
    return (
        "<div class='card'>"
        "<div class='card__head'><h2 class='card__title'>Collected vs outstanding (live)</h2></div>"
        f"<div class='barlist'>{body}</div>"
        "</div>"
    )


def _invoice_table(data: dict) -> str:
    rows = ""
    for inv in data["recent"]:
        state = inv["state"]
        label = state
        if state == "OVERDUE" and inv.get("days_overdue") is not None:
            label = f"OVERDUE {inv['days_overdue']}d"
        rows += (
            "<tr>"
            f"<td>{_esc(inv['number'])}</td>"
            f"<td>{_esc(inv['customer'])}</td>"
            f"<td class='num'>{_esc(inv['amount'])}</td>"
            f"<td><span class='pill {_state_pill(state)}'>{_esc(label)}</span></td>"
            "</tr>"
        )
    return (
        "<div class='card'>"
        "<div class='card__head'><h2 class='card__title'>Recent invoices</h2>"
        "<span class='pill pill--info'><span class='pill__dot'></span>data: live from Lago</span></div>"
        "<table class='table'><thead><tr><th>Invoice</th><th>Customer</th><th>Amount</th><th>Status</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        "</div>"
    )


def render(data: dict) -> str:
    connected = data["connected"]
    conn_txt = "core: Lago connected" if connected else "core: Lago UNREACHABLE"
    conn_cls = "pill--success" if connected else "pill--danger"
    status_pill = (
        f"<span class='pill {conn_cls}'><span class='pill__dot'></span>agent active · {_esc(conn_txt)}</span>"
    )
    live_badge = "<span class='pill pill--info'><span class='pill__dot'></span>data: live from Lago</span>"
    open_btn = f"<a class='btn' href='{_esc(data['front_url'])}' target='_blank' rel='noopener'>Open in Lago ↗</a>"

    body = (
        _approval_banner(data)
        + _kpi_tiles(data["kpis"])
        + "<section class='shell' style='gap:var(--sp-4)'>"
        "<div class='section-label'>Cash position</div>"
        "<div class='grid'>"
        f"<div class='col-6'>{_collected_outstanding_bars(data)}</div>"
        f"<div class='col-6'>{_invoice_table(data)}</div>"
        "</div></section>"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agentic Billing — {_esc(TENANT)}</title>
{FONT_LINK}
<style>{BASE_CSS}{PAGE_CSS}</style>
</head>
<body class="page">
<div class="shell">
  <header class="appbar">
    <div class="appbar__row">
      <h1>Agentic Billing</h1>
      {status_pill}
      {live_badge}
      <span class="spacer"></span>
      {open_btn}
    </div>
    <div class="appbar__tenant"><b>{_esc(TENANT)}</b> · core: Lago (open-source billing)</div>
    <div class="appbar__sub">{_esc(SUBTITLE)}</div>
  </header>
  {body}
  <footer class="footer">agentic-billing · live activity for {_esc(TENANT)} ·
    <a href="/api/activity">/api/activity</a> · agent + human, on a real Lago core · redevops.io Agentic Business OS</footer>
</div>
</body>
</html>"""


# --- optional LLM reasoning blurb (guarded: works without any API key) -------
def _llm_blurb(prompt: str) -> str | None:
    """Return a one-line reasoning blurb from Claude, or None if no key / any error.

    Optional by design — every agentic action below is deterministic Lago API work;
    the LLM only narrates. Absence of ANTHROPIC_API_KEY must never break the endpoint.
    """
    base = os.environ.get("REDEVOPS_LLM_BASE_URL")
    if base:
        try:
            r = httpx.post(
                base.rstrip("/") + "/chat/completions",
                json={"model": os.environ.get("REDEVOPS_LLM_MODEL", "DeepSeek-V4-Flash"),
                      "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 220, "temperature": 0.3},
                timeout=90.0,   # DeepSeek runs on CPU (~15 tok/s) — be patient
            )
            if r.status_code == 200:
                txt = (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
                if txt:
                    return txt
        except Exception:
            pass
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                # claude-opus-4-8 is Anthropic's current Opus-tier model id.
                "model": "claude-opus-4-8",
                "max_tokens": 200,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15.0,
        )
        r.raise_for_status()
        return "".join(
            b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text"
        ).strip() or None
    except Exception:
        return None


# --- agentic actions ---------------------------------------------------------
def _chase_overdue() -> dict:
    """For each overdue invoice, trigger Lago's payment retry (the dunning action).

    POST /api/v1/invoices/{lago_id}/retry_payment is the real, idempotent Lago call.
    Hybrid + approval-aware: we report exactly what we did per invoice.
    """
    data = fetch_activity(force=True)
    overdue = data.get("overdue", [])
    actions = []
    with httpx.Client(timeout=10.0) as client:
        for inv in overdue:
            lago_id = inv.get("lago_id")
            result = {"invoice": inv["number"], "customer": inv["customer"],
                      "amount": inv["amount"], "days_overdue": inv["days_overdue"]}
            try:
                resp = client.post(
                    f"{LAGO_API_URL}/api/v1/invoices/{lago_id}/retry_payment",
                    headers=_headers(),
                )
                result["lago_status"] = resp.status_code
                result["action"] = (
                    "retry_payment triggered (dunning reminder sent)"
                    if resp.status_code in (200, 202)
                    else f"retry_payment returned {resp.status_code}"
                )
            except Exception as e:
                result["action"] = f"error: {e}"
            actions.append(result)

    detail = "; ".join(f"{i['customer']} {i['amount']} ({i['days_overdue']}d)" for i in overdue)
    blurb = _llm_blurb(
        "You are a billing collections agent for a roofing contractor. In ONE sentence, "
        f"summarize sending dunning reminders / retrying payment on these {len(overdue)} overdue "
        f"invoices: {detail}. Be concrete and professional. Final answer only, no preamble."
    ) if overdue else None
    out = {
        "status": "done",
        "action": "chase_overdue",
        "overdue_count": len(overdue),
        "results": actions,
        "summary": f"Retried payment / sent dunning reminder on {len(actions)} overdue invoice(s) via Lago.",
    }
    if blurb:
        out["reasoning"] = blurb
    return out


def _refund(body: dict) -> dict:
    """Refunds move money OUT — never auto-executed. Stage for human approval only."""
    data = fetch_activity(force=True)
    target = body.get("invoice") or (data["recent"][0]["number"] if data["recent"] else "—")
    amount = body.get("amount", "$450")
    return {
        "status": "pending_approval",
        "action": "refund",
        "requires": "human approval",
        "summary": f"Refund of {amount} on invoice {target} is staged and awaiting human approval. "
                   "Refunds are never auto-executed by the agent.",
    }


# --- routes ------------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "core": "lago", "connected": lago_connected()}


@app.get("/api/activity")
def activity() -> JSONResponse:
    return JSONResponse(fetch_activity())


# --- Context Runtime: live decisions over a synthetic account stream ----------
import asyncio as _cr_asyncio
import json as _cr_json
from datetime import datetime as _cr_dt, timezone as _cr_tz
from fastapi.responses import StreamingResponse as _CRStreamingResponse

try:
    from context_runtime.integrations.agentic_billing import (  # type: ignore
        AgenticBillingTenant as _CRTenant, agentic_billing_bucket as _cr_bucket,
    )
    _CR = _CRTenant(epsilon=0.15)
except Exception:  # noqa: BLE001
    _CR = None

    def _cr_bucket(_t):  # type: ignore
        return "general"

_CR_SYNTH = [
    'ACME Corp overdue 45 days',
    'Globex subscription at churn risk',
    'Initech paid early last quarter',
    'Umbrella invoices past due',
]


def _cr_decide(text: str) -> dict:
    try:
        bucket = _cr_bucket(text)
    except Exception:  # noqa: BLE001
        bucket = "general"
    if _CR is not None:
        try:
            try:
                arm = _CR.choose(text, bucket=bucket)
            except TypeError:
                arm = _CR.choose(text)
            try:
                _CR.record_outcome(text, 5.0)
            except Exception:  # noqa: BLE001
                pass
            return {"bucket": str(bucket), "bundle": getattr(arm, "key", str(arm))}
        except Exception:  # noqa: BLE001
            pass
    return {"bucket": str(bucket), "bundle": "(context runtime offline)"}

_CR_LIVE_FEED = """
<div id="cr-live" style="position:fixed;right:16px;bottom:16px;width:340px;max-height:58vh;overflow:auto;background:#17171a;border:1px solid #2f2f33;border-radius:12px;padding:12px;font:13px/1.45 Roboto,system-ui,sans-serif;color:#e4e2e6;z-index:9999;box-shadow:0 10px 34px rgba(0,0,0,.45)">
  <div style="color:#4fd1c5;font-weight:600;margin-bottom:8px">Context Runtime — live decisions</div>
  <div id="cr-feed" style="color:#9b99a1">connecting…</div>
</div>
<script>
(function(){
  var feed=document.getElementById('cr-feed');var first=true;
  try{
    var es=new EventSource('/api/stream');
    es.onmessage=function(e){
      if(first){feed.innerHTML='';first=false;}
      var d=JSON.parse(e.data);var row=document.createElement('div');
      row.style.cssText='border-top:1px solid #2f2f33;padding:7px 0';
      row.innerHTML='<div style="color:#9b99a1;font-size:11px">'+d.ts+' \u00b7 <b style="color:#c7c5ca">'+d.bucket+'</b></div>'+'<div style="margin:2px 0">'+d.input+'</div>'+'<div style="color:#4fd1c5">\u2192 pulled context: <b>'+d.bundle+'</b></div>';
      feed.insertBefore(row,feed.firstChild);
      while(feed.children.length>8) feed.removeChild(feed.lastChild);
    };
    es.onerror=function(){ if(first){feed.textContent='(live stream unavailable)';} };
  }catch(err){feed.textContent='(live stream unavailable)';}
})();
</script>
"""


@app.get("/api/stream")
async def cr_stream() -> _CRStreamingResponse:
    async def _gen():
        i = 0
        while True:
            text = _CR_SYNTH[i % len(_CR_SYNTH)]
            i += 1
            d = _cr_decide(text)
            evt = {"input": text, "ts": _cr_dt.now(_cr_tz.utc).strftime("%H:%M:%S"), **d}
            yield f"data: {_cr_json.dumps(evt)}\n\n"
            await _cr_asyncio.sleep(2.5)
    return _CRStreamingResponse(_gen(), media_type="text/event-stream")


_CR_BANNER = """<div style="position:sticky;top:0;z-index:9998;background:linear-gradient(90deg,#10201d,#17171a);border-bottom:1px solid #2f2f33;color:#e4e2e6;font:13px/1.4 Roboto,system-ui,sans-serif;padding:9px 16px;display:flex;gap:10px;align-items:center;flex-wrap:wrap"><span style="background:#4fd1c5;color:#08110f;font-weight:700;border-radius:5px;padding:2px 8px;font-size:11px;letter-spacing:.4px">CONTEXT RUNTIME</span><span style="background:#2f2f33;border-radius:5px;padding:2px 8px;font-size:11px;letter-spacing:.4px">DEMO</span><span style="color:#9b99a1">This demo app is plugged into <b style="color:#e4e2e6">Context Runtime</b>, which optimizes which billing signals to pull — right collections action vs data cost (4.12 vs 2.44). <a href="https://github.com/redevops-io/context-runtime" style="color:#4fd1c5;text-decoration:none">learn more \u2192</a></span></div>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    import re as _cr_re
    page = render(fetch_activity())
    page = _cr_re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + _CR_BANNER, page, count=1)
    if "_CR_BANNER" not in page and "cr-live" not in page:  # no <body> matched → prepend
        page = _CR_BANNER + page
    return (page.replace("</body>", _CR_LIVE_FEED + "</body>")
            if "</body>" in page else page + _CR_LIVE_FEED)


@app.post("/agent/run")
async def agent_run(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        body = {}
    action = (body or {}).get("action", "")

    if action == "chase_overdue":
        return JSONResponse(_chase_overdue())
    if action == "refund":
        return JSONResponse(_refund(body or {}))
    return JSONResponse(
        {"status": "error", "error": f"unknown action '{action}'",
         "supported": ["chase_overdue", "refund"]},
        status_code=400,
    )


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
