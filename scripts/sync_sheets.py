"""Sincroniza Finanzas y la cartera de Leads a Google Sheets — en vivo, sin
que nadie tenga que abrir el dashboard ni descargar/pegar nada a mano
(pedido por Diego, 2026-07-20).

Reutiliza api.py::_accounts_and_mrr() para el cálculo de MRR — el mismo que
usa /api/accounts y /api/finance — así el Sheet NUNCA muestra un número
distinto al que ve Diego en el dashboard.

Uso: python3 scripts/sync_sheets.py
Necesita en el entorno: GOOGLE_SHEETS_KEY_PATH, GOOGLE_SHEETS_ID (ver
zero/sheets.py para el detalle de cada uno).

Pensado para correr cada cierto tiempo vía systemd timer (mismo patrón que
scripts/supabase_keepalive.py) — ver docs/motor-real.md o el
.service/.timer instalados en el Ubuntu de producción.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zero._env import load_env  # noqa: E402

load_env()

import api  # noqa: E402 — reutiliza _crm()/_accounts_and_mrr()/FINANCE_PATH tal cual los usa la API real
from zero.finance import finance_summary  # noqa: E402
from zero.sheets import sync_all  # noqa: E402


def main() -> int:
    spreadsheet_id = os.environ.get("GOOGLE_SHEETS_ID")
    if not spreadsheet_id:
        print("[sync_sheets] falta GOOGLE_SHEETS_ID en el entorno — nada que sincronizar.")
        return 0   # no es un error de infraestructura, es "todavía no configurado"

    crm = api._crm()
    _, mrr = api._accounts_and_mrr()
    finance_data = finance_summary(api.FINANCE_PATH, mrr_clp=mrr)
    leads = crm.all_leads()

    result = sync_all(spreadsheet_id, finance_data, leads)
    ok_finance = bool(result.get("finance"))
    ok_leads = bool(result.get("leads"))
    print(f"[sync_sheets] finanzas: {'ok' if ok_finance else 'FALLÓ'} · "
          f"leads: {'ok' if ok_leads else 'FALLÓ'} ({len(leads)} en total)"
          + (f" · {result['error']}" if result.get("error") else ""))
    return 0 if (ok_finance and ok_leads) else 1


if __name__ == "__main__":
    raise SystemExit(main())
