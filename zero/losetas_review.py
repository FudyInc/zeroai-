"""LosetasChile: the owner's answer to a review draft becomes the final budget.

The review group holds the internal draft the agent published. The owner quotes
it with the missing data (shipping, dates, address...); this module reads that
answer and builds the two messages posted back in the SAME group, never to the
customer. Reading and composing are pure; only `handle_review_message` touches
memory and the bridge.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
import unicodedata
from datetime import date as Date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .attention import fixed_answer
from .config import (LOSETASCHILE_DEPOSIT_CLP, REVIEW_DATE_ROLLOVER_DAYS, REVIEW_DRAFTS_KEPT,
                     REVIEW_MIN_SHIPPING_CLP, WHATSAPP_TIME_ZONE, POOLEDGE_ORDERS_SHEET_ENV,
                     POOLEDGE_TAB_INFO, POOLEDGE_TAB_PLATAS_NEW, POOLEDGE_WRITE_ORDERS,
                     POOLEDGE_WRITING_STALE_MINUTES)
from .losetas_budget import format_customer_budget
from .pooledge_orders import (OrderError, build_order_rows, existing_order_ids, find_order_row,
                              first_free_row, next_order_id, INFO_DATA_COLUMNS,
                              PLATAS_DATA_COLUMNS)

_WEEKDAYS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
_MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
           "septiembre", "octubre", "noviembre", "diciembre")
_WD = "|".join(_WEEKDAYS)
_MONTH_NUMBER = {name: n for n, name in enumerate(_MONTHS, 1)} | {"setiembre": 9}
_MONTH_RE = "|".join(_MONTH_NUMBER)
_URL = re.compile(r"(?:https?://)?(?:maps\.app\.goo\.gl|goo\.gl/maps|(?:www\.)?google\.com/maps)"
                  r"[^\s]*", re.I)
_NUMERIC_DATE = re.compile(
    rf"(?:\b({_WD})\s+)?(?<!\d)(\d{{1,2}})[/-](\d{{1,2}})(?:[/-](\d{{4}}|\d{{2}}))?(?!\d)")
_WORD_DATE = re.compile(
    rf"(?:\b({_WD})\s+)?(?<![\d/])(\d{{1,2}})(?:\s+de\s+({_MONTH_RE})(?:\s+(?:de\s+)?(\d{{4}}))?)?\b")
# Sizes and time slots hold numbers that are not delivery days.
_NOT_DATES = re.compile(
    r"\d+(?:[.,]\d+)?\s*[x×]\s*\d+(?:[.,]\d+)?(?:\s*(?:m|mts|metros)\b)?|"
    r"\b\d{1,2}(?::\d{2})?(?:\s*(?:-|a|y)\s*\d{1,2}(?::\d{2})?)?\s*(?:hrs?|horas?|h)\b")
_AMOUNT = re.compile(r"(\d+(?:[.,]\d+)?)\s*mil\b|\$\s*(\d[\d.,]*)|"
                     r"\b(\d{1,3}(?:[.,]\d{3})+)\b|\b(\d{4,})\b", re.I)
_REGION = re.compile(r"^(.*?),\s*(?:(?:[ivxl]+\s+)?regi[oó]n\b.*|rm)\s*$", re.I)
_NOT_PLACE = re.compile(r"^(avenida|av|calle|pasaje|casa|depto|departamento|poste|parcela|"
                        r"sitio|lote|villa|poblaci[oó]n|camino|ruta|condominio)\b", re.I)

# Fase 2: palabras clave del dueño para escribir en la planilla
_CONFIRM_WORD = re.compile(r"confirmado\W*")
_OK_WORD = re.compile(r"(?:ok|okay|oka)\W*")
# Estados del borrador en que la fase 2 manda: con el flag encendido, nada más los toca.
_PHASE2_STATUSES = ("final_published", "preview_sent", "sheet_writing", "sheet_written")
# `handle_review_message` NO corre serializado: api.py::_process_inbound_messages se ejecuta
# en el threadpool de BackgroundTasks y en el worker de la bandeja, cada uno con su propia
# SessionMemory. Este lock serializa la sección crítica de la escritura en la planilla
# (dentro de un mismo proceso); dentro se recarga el estado desde disco para ver lo que
# otro hilo haya guardado mientras esperaba.
_WRITE_LOCK = threading.Lock()
_SHEET_ERROR = "*POOLEDGE* No pude anotar el pedido en la planilla. Detalle en el registro."


def _plain(text: str) -> str:
    folded = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in folded if unicodedata.category(ch) != "Mn").casefold()


def text_key(text: str) -> str:
    """Hash of a draft's text, tolerant to the formatting WhatsApp may strip when quoting."""
    flat = " ".join(re.sub(r"[*_~]", "", text or "").split()).casefold()
    return hashlib.sha256(flat.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(ZoneInfo(WHATSAPP_TIME_ZONE))


def today() -> Date:
    return datetime.now(ZoneInfo(WHATSAPP_TIME_ZONE)).date()


# --- drafts in memory --------------------------------------------------------

def store_review_draft(memory: Any, client_id: str, group_message_id: str,
                       draft: dict[str, Any]) -> None:
    """Remember a published draft by group message id and by text hash; keep the last N."""
    bucket = memory.clients.setdefault(client_id, {})
    drafts = bucket.setdefault("review_drafts", {})
    index = bucket.setdefault("review_draft_index", {})
    drafts[group_message_id] = dict(draft, status="pending")
    index[text_key(draft.get("text", ""))] = group_message_id
    while len(drafts) > REVIEW_DRAFTS_KEPT:
        drafts.pop(next(iter(drafts)))
    for key in [k for k, v in index.items() if v not in drafts]:
        del index[key]


def find_review_draft(memory: Any, client_id: str, quoted_id: str,
                      quoted_text: str) -> tuple[str, dict[str, Any]] | None:
    bucket = memory.clients.get(client_id, {})
    drafts = bucket.get("review_drafts") or {}
    if quoted_id and quoted_id in drafts:
        return quoted_id, drafts[quoted_id]
    linked = (bucket.get("review_draft_index") or {}).get(quoted_id) if quoted_id else None
    if linked in drafts:
        return linked, drafts[linked]
    found = (bucket.get("review_draft_index") or {}).get(text_key(quoted_text)) \
        if quoted_text else None
    if found and found in drafts:
        return found, drafts[found]
    return None


def link_followup(memory: Any, client_id: str, draft_id: str, text: str,
                  sent: dict[str, Any]) -> None:
    """A "Falta:" post the owner may quote: its id and text hash lead back to the draft."""
    index = memory.clients.setdefault(client_id, {}).setdefault("review_draft_index", {})
    index[text_key(text)] = draft_id
    if sent.get("id"):
        index[str(sent["id"])] = draft_id


# --- reading the owner's answer ----------------------------------------------

def _amount(text: str) -> int | None:
    digits = re.sub(r"\D", "", text)
    return int(digits) if digits else None


def _place_from_address(address: str) -> str | None:
    """Conservative: only the segment right before an explicit region suffix."""
    found = _REGION.match(address)
    if not found:
        return None
    parts = [part.strip() for part in found.group(1).split(",")]
    last = parts[-1]
    if (len(parts) < 2 or not re.fullmatch(r"[^\W\d_]+(?: [^\W\d_]+){0,2}", last) or
            _NOT_PLACE.match(last)):
        return None
    return last


_BLANK = {"shipping": None, "place": None, "address": None, "map_url": None,
          "pool": None, "delivery": [], "pickup_line": False, "shipping_line": False}


def _shipping_amount(rest: str) -> tuple[int | None, str | None, str]:
    """(amount, problem, leftover text): only an unambiguous figure of 1000 or more counts."""
    values, left, last = set(), [], 0
    for m in _AMOUNT.finditer(rest):
        if m.group(1):
            values.add(round(float(m.group(1).replace(",", ".")) * 1000))
        else:
            values.add(int(re.sub(r"\D", "", m.group(2) or m.group(3) or m.group(4))))
        left.append(rest[last:m.start()])
        last = m.end()
    left.append(rest[last:])
    leftover = "".join(left)
    if len(values) == 1 and min(values) >= REVIEW_MIN_SHIPPING_CLP:
        return values.pop(), None, leftover
    if values or re.search(r"\d", rest):
        return None, "monto de despacho", leftover
    return None, None, leftover


def _dates(line: str, issued: Date, problems: list[str]) -> list[Date]:
    plain = _NOT_DATES.sub(" ", _plain(line))
    found: list[tuple[str | None, int, int, int | None]] = []
    for m in _NUMERIC_DATE.finditer(plain):
        year = int(m.group(4)) if m.group(4) else None
        found.append((m.group(1), int(m.group(2)), int(m.group(3)),
                      year + 2000 if year is not None and year < 100 else year))
    if not found and re.search(rf"\b(?:{_MONTH_RE})\b", plain):
        # A bare number is a day only when chained with "y"/"o"/"," to a token with a month.
        tokens = list(_WORD_DATE.finditer(plain))
        month = year = None
        for n in range(len(tokens) - 1, -1, -1):
            m = tokens[n]
            joined = (n + 1 < len(tokens) and
                      plain[m.end():tokens[n + 1].start()].strip() in (",", "y", "o"))
            if m.group(3):
                month = _MONTH_NUMBER[m.group(3)]
                year = int(m.group(4)) if m.group(4) else None
            elif not joined:
                month = year = None
            if month:
                found.append((m.group(1), int(m.group(2)), month, year))
        found.reverse()
    days: list[Date] = []
    for weekday, day, month, year in found:
        try:
            when = Date(year or issued.year, month, day)
            if year is None and when < issued:
                if (issued - when).days <= REVIEW_DATE_ROLLOVER_DAYS:
                    problems.append(f"fecha anterior a hoy ({day}/{month})")
                    continue
                when = Date(issued.year + 1, month, day)
        except ValueError:
            problems.append(f"fecha inválida ({day}/{month})")
            continue
        if weekday and _WEEKDAYS.index(weekday) != when.weekday():
            problems.append(f"{weekday} no cae el {day}/{month} "
                            f"(es {_WEEKDAYS[when.weekday()]})")
            continue
        days.append(when)
    return days


def read_owner_reply(text: str, draft: dict[str, Any],
                     issued: Date | None = None) -> dict[str, Any]:
    """Pull the data fields out of the owner's free-form lines.

    Data from an earlier reply (draft["partial"]) is combined; what is new wins."""
    issued = issued or Date.fromisoformat(draft["issued"])
    new = dict(_BLANK, delivery=[])
    problems: list[str] = []
    recognized = False
    detail = str(draft.get("quote", {}).get("delivery_detail") or "")
    shared = re.search(r"Ubicación compartida:\s*(\S+)", detail)
    for raw in (text or "").splitlines():
        link = _URL.search(raw)
        if link:
            url = link.group(0).rstrip(".,;)")
            new["map_url"] = url if url.startswith("http") else "https://" + url
            recognized = True
        line = _URL.sub(" ", raw).strip()
        plain = _plain(line)
        label = re.match(r"\s*(despacho|flete|direccion|dir)\b\.?\s*:?\s*(.*)$", plain)
        if re.match(r"retiro\b", plain):
            new["pickup_line"] = recognized = True
        elif label and label.group(1) in ("despacho", "flete"):
            recognized = new["shipping_line"] = True
            rest = line[len(line) - len(label.group(2)):] if label.group(2) else ""
            amount, problem, rest = _shipping_amount(rest)
            if problem:
                problems.append(problem)
            if amount is not None:
                new["shipping"] = amount
            rest = re.sub(r"\([^)]*\)", " ", rest)
            place = re.sub(r"^[\s:\-–]*(?:(?:a|para|en|hacia)\s+)?", "", rest, flags=re.I)
            place = re.sub(r"[\s$:\-–]*(?:clp|pesos)?[\s$]*$", "", place, flags=re.I).strip()
            if place:
                new["place"] = place.title() if place.islower() else place
        elif label:
            recognized = True
            address = line[len(line) - len(label.group(2)):].strip() if label.group(2) else ""
            if address:
                new["address"] = address
        else:
            pool = (re.search(r"piscina[^\d\n]{0,15}(\d+(?:[.,]\d+)?)\s*[x×]\s*(\d+(?:[.,]\d+)?)",
                              plain) or
                    re.search(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*[x×]\s*(\d+(?:[.,]\d+)?)"
                              r"\s*(?:m|mts|metros)\b", plain))
            if pool:
                new["pool"] = f"{pool.group(1)} × {pool.group(2)} m"
                recognized = True
            days = _dates(line, issued, problems)
            if days:
                recognized = True
                new["delivery"].extend(days)
    old = draft.get("partial") or {}
    fields = {key: new[key] if new[key] not in (None, [], False) else old.get(key, new[key])
              for key in _BLANK}
    new_days = sorted(set(new["delivery"]))
    fields["delivery"] = new_days or [Date.fromisoformat(d) for d in old.get("delivery", [])]
    partial = dict(fields, delivery=[d.isoformat() for d in fields["delivery"]])
    fields["pickup"] = detail.startswith("Retiro en fábrica") or bool(fields["pickup_line"])
    if fields["pickup"] and fields["shipping_line"]:
        problems.append("despacho y retiro a la vez")
    if fields["pickup"]:
        fields["shipping"] = 0
    if not fields["map_url"] and shared:
        fields["map_url"] = shared.group(1)
    if not fields["place"] and fields["address"]:
        fields["place"] = _place_from_address(fields["address"])
    missing = []
    if not fields["pickup"]:
        if fields["shipping"] is None and "monto de despacho" not in problems:
            missing.append("despacho")
        if not fields["address"]:
            missing.append("dirección")
    if not fields["delivery"]:
        missing.append("fecha")
    return {"fields": fields, "missing": missing, "problems": problems,
            "recognized": recognized, "partial": partial}


# --- composing the two messages ----------------------------------------------

_BANK_LINE = re.compile(r"^\s*[-*•]?\s*(nombre|rut|banco|cuenta[^:]*|correo)\s*:", re.I)


def bank_block(knowledge: str) -> str | None:
    """Transfer details exactly as the client sheet states them; never invented."""
    body = fixed_answer(knowledge, "medios de pago") or ""
    lines = [re.sub(r"^\s*[-*•]\s*", "", line).strip()
             for line in body.splitlines() if _BANK_LINE.match(line)]
    return "\n".join(lines) or None


def _money(amount: float) -> str:
    return "$" + f"{round(amount):,}".replace(",", ".")


def final_messages(draft: dict[str, Any], reading: dict[str, Any], knowledge: str,
                   issued: Date | None = None) -> dict[str, Any]:
    """What to post in the group. `budget`/`payment` say which of the messages are
    the final budget and the payment message; no messages means stay silent."""
    def only(*texts: str) -> dict[str, Any]:
        return {"messages": list(texts), "budget": False, "payment": False}

    if not reading["recognized"]:
        return only()
    fields, missing, problems = reading["fields"], reading["missing"], reading["problems"]
    if missing or problems:
        parts = ([f"Falta: {', '.join(missing)}"] if missing else []) + \
                ([f"No cuadra: {'; '.join(problems)}"] if problems else [])
        return only(" · ".join(parts))
    issued = issued or Date.fromisoformat(draft["issued"])
    quote = draft["quote"]
    phone = re.sub(r"\D", "", draft.get("phone") or "")
    name = draft.get("name") or ""
    label = f"Despacho a {fields['place']}" if fields["place"] else "Despacho"
    budget = format_customer_budget(
        quote, number=f"PE-{issued:%d%m%y}-{phone[-4:]}", issued=issued,
        customer=name if any(c.isalpha() for c in name) else "Cliente", phone=phone,
        address=fields["address"], color=draft.get("color"), pool=fields["pool"],
        shipping=fields["shipping"], shipping_label=label,
        delivery=fields["delivery"], deposit=LOSETASCHILE_DEPOSIT_CLP,
        map_url=fields["map_url"], pickup=fields["pickup"])
    if budget is None:
        early = any(day < issued for day in fields["delivery"])
        return only("No cuadra: " + ("fecha anterior a la emisión" if early else
                                     "cifras o datos del presupuesto no son consistentes"))
    total = quote["total"] + (fields["shipping"] or 0)
    bank = bank_block(knowledge)
    if not bank:
        return {"messages": [budget, "Falta en la ficha: datos de transferencia"],
                "budget": True, "payment": False}
    payment = (f"Para confirmar su pedido se hace un abono de {_money(LOSETASCHILE_DEPOSIT_CLP)} "
               f"y el resto ({_money(total - LOSETASCHILE_DEPOSIT_CLP)}) se paga contra entrega, "
               f"en efectivo o por transferencia.\n\nDatos para la transferencia:\n{bank}\n\n"
               "Cuando haga el abono, envíenos el comprobante por este chat.")
    return {"messages": [budget, payment], "budget": True, "payment": True}


# --- the one entry point that touches memory and the bridge ------------------

def _is_confirm(text: str) -> bool:
    return bool(_CONFIRM_WORD.fullmatch((text or "").strip().casefold()))


def _is_ok(text: str) -> bool:
    return bool(_OK_WORD.fullmatch((text or "").strip().casefold()))


def _preview_text(draft: dict[str, Any], rows: dict[str, list]) -> str:
    """Texto de vista previa que el bot publica en el grupo antes de escribir."""
    platas, info = rows["platas_row"], rows["info_row"]
    line = (f"*POOLEDGE* Voy a anotar en la planilla:\n"
            f"• ID: se asigna al anotar (hoy sería {rows['order_id']})\n"
            f"• Cliente: {draft.get('name') or ''}\n"
            f"• Detalle: {platas[3] or ''}\n"
            f"• Venta neta: {_money(platas[4])}\n"
            f"• Despacho: {_money(info[7])}\n"
            f"• Fecha: {platas[1]}")
    if info[4]:
        line += f"\n• Lugar: {info[4]}"
    return line + "\n\nResponde *ok* citando este mensaje para confirmar."


def _json_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Los campos leídos con las fechas en ISO: el estado se guarda con json.dumps."""
    return {key: ([d.isoformat() if isinstance(d, Date) else d for d in value]
                  if key == "delivery" else value) for key, value in fields.items()}


def _sheet_session() -> tuple[Any, str, str]:
    from . import sheets
    spreadsheet_id = os.environ.get(POOLEDGE_ORDERS_SHEET_ENV)
    if not spreadsheet_id:
        raise RuntimeError("falta la planilla de pedidos en el entorno")
    token = sheets.get_access_token()
    if not token:
        raise RuntimeError("sin autorización para Sheets")
    return sheets, spreadsheet_id, token


def _read_tabs(sheets: Any, spreadsheet_id: str, token: str):
    info_tab = sheets.quote_tab(POOLEDGE_TAB_INFO)
    platas_tab = sheets.quote_tab(POOLEDGE_TAB_PLATAS_NEW)
    info = sheets.read_values(spreadsheet_id, f"{info_tab}!A:J", token)
    platas = sheets.read_values(spreadsheet_id, f"{platas_tab}!A:E", token)
    return info_tab, platas_tab, info, platas


def _say(whatsapp_web: Any, client_id: str, message: dict[str, str], text: str) -> dict[str, Any]:
    return whatsapp_web.send_group_text(client_id, message["to_phone_id"],
                                        message["chat_id"], text)


def _tell(whatsapp_web: Any, client_id: str, message: dict[str, str], text: str) -> None:
    try:
        _say(whatsapp_web, client_id, message, text)
    except (RuntimeError, ValueError):
        pass


def _publish_preview(memory: Any, whatsapp_web: Any, client_id: str, draft_id: str,
                     draft: dict[str, Any], message: dict[str, str]) -> None:
    """"confirmado" sobre el presupuesto final: arma las filas y publica la vista previa.
    El ID de la vista previa es tentativo: el definitivo se asigna al anotar."""
    fields = draft.get("fields")
    if not fields:
        _tell(whatsapp_web, client_id, message,
              "*POOLEDGE* Este presupuesto es anterior a la carga automática; anótalo a mano.")
        return
    rows = None
    try:
        sheets, spreadsheet_id, token = _sheet_session()
        info = _read_tabs(sheets, spreadsheet_id, token)[2]
        rows = build_order_rows(draft, fields, next_order_id(existing_order_ids(info)))
        text = _preview_text(draft, rows)
    except OrderError as exc:
        rows = None
        text = (f"*POOLEDGE* No puedo anotar aún: {exc}. "
                "Completa los datos y responde «confirmado» de nuevo.")
    except Exception as exc:
        rows = None
        memory.log("order_preview_failed", client=client_id, lead=draft.get("lead"),
                   error=type(exc).__name__)
        text = _SHEET_ERROR
    try:
        result = _say(whatsapp_web, client_id, message, text)
    except (RuntimeError, ValueError) as exc:
        memory.log("order_preview_send_uncertain", client=client_id,
                   lead=draft.get("lead"), error=type(exc).__name__)
        return
    if not rows:
        return
    link_followup(memory, client_id, draft_id, text, result)
    draft["preview"] = rows
    draft["preview_msg_id"] = result.get("id")
    draft["status"] = "preview_sent"
    memory.save()
    memory.log("order_preview_posted", client=client_id, lead=draft.get("lead"),
               order_id=rows["order_id"])


def _stale(draft: dict[str, Any]) -> bool:
    started = draft.get("sheet_writing_at")
    try:
        age = _now() - datetime.fromisoformat(started)
    except (TypeError, ValueError):
        return True
    return age.total_seconds() > POOLEDGE_WRITING_STALE_MINUTES * 60


def _write_order(memory: Any, whatsapp_web: Any, client_id: str, draft_id: str,
                 message: dict[str, str]) -> None:
    """"ok" sobre la vista previa: escribe las dos pestañas, una sola vez por borrador.
    La protección contra doble escritura es el estado del propio borrador, releído desde
    disco dentro del lock: otro hilo pudo escribirlo mientras este esperaba."""
    notice, stage, marked, order_id = "", "read", False, ""
    draft: dict[str, Any] = {}
    try:
        with _WRITE_LOCK:
            memory.reload()
            draft = ((memory.clients.get(client_id) or {}).get("review_drafts") or {}
                     ).get(draft_id) or {}
            status = draft.get("status")
            order_id = draft.get("order_id") or ""
            if status == "sheet_written":
                notice = f"*POOLEDGE* Ya anotado como {order_id}. No se vuelve a escribir."
            elif status == "sheet_writing" and not _stale(draft):
                notice = ("*POOLEDGE* Se está anotando en la planilla (en proceso). Si pasan "
                          f"{POOLEDGE_WRITING_STALE_MINUTES} minutos sin aviso, responde *ok* "
                          "de nuevo y lo verifico antes de reintentar.")
            elif status in ("preview_sent", "sheet_writing"):
                sheets, spreadsheet_id, token = _sheet_session()
                info_tab, platas_tab, info, platas = _read_tabs(sheets, spreadsheet_id, token)
                known = find_order_row(info, order_id) if (
                    status == "sheet_writing" and order_id) else None
                if known:
                    # Pegado: la escritura anterior sí se aplicó, solo se marca.
                    draft["status"] = "sheet_written"
                    memory.save()
                    notice = f"*POOLEDGE* Ya anotado como {order_id} (INFO fila {known})."
                else:
                    order_id = next_order_id(existing_order_ids(info))
                    rows = build_order_rows(draft, draft["fields"], order_id)
                    info_row = first_free_row(info, INFO_DATA_COLUMNS)
                    platas_row = first_free_row(platas, PLATAS_DATA_COLUMNS)
                    # Marcar ANTES de escribir: un segundo "ok" no vuelve a entrar.
                    draft["status"] = "sheet_writing"
                    draft["order_id"] = order_id
                    draft["sheet_writing_at"] = _now().isoformat()
                    marked = True
                    memory.save()
                    stage = "write"
                    sheets.batch_values_update(spreadsheet_id, [
                        {"range": f"{info_tab}!A{info_row}:J{info_row}",
                         "values": [rows["info_row"]]},
                        {"range": f"{platas_tab}!A{platas_row}:B{platas_row}",
                         "values": [rows["platas_row"][0:2]]},
                        {"range": f"{platas_tab}!D{platas_row}:E{platas_row}",
                         "values": [rows["platas_row"][3:5]]},
                    ], token)
                    draft["status"] = "sheet_written"
                    draft["sheet_row"] = {"info": info_row, "platas": platas_row}
                    memory.save()
                    stage = "done"
    except Exception as exc:
        memory.log("order_sheet_failed", client=client_id, lead=draft.get("lead"),
                   order_id=order_id, stage=stage, error=type(exc).__name__)
        if stage == "write":
            # Resultado incierto: pudo aplicarse. Queda en "sheet_writing" y el "ok"
            # siguiente (pasado el plazo) lo verifica en INFO antes de reintentar.
            notice = ("*POOLEDGE* No sé si quedó anotado. En "
                      f"{POOLEDGE_WRITING_STALE_MINUTES} minutos responde *ok* de nuevo y lo "
                      "verifico antes de reintentar.")
        else:
            if marked:
                # No se llegó a llamar a la API: nada se escribió, el "ok" puede reintentar ya.
                draft["status"] = "preview_sent"
                try:
                    memory.save()
                except Exception:
                    pass
            notice = _SHEET_ERROR
        _tell(whatsapp_web, client_id, message, notice)
        return
    if stage != "done":
        if notice:
            _tell(whatsapp_web, client_id, message, notice)
        return
    memory.log("order_sheet_written", client=client_id, lead=draft.get("lead"),
               order_id=order_id, info_row=draft["sheet_row"]["info"],
               platas_row=draft["sheet_row"]["platas"])
    try:
        _say(whatsapp_web, client_id, message,
             f"*POOLEDGE* Anotado en la planilla: {order_id} "
             f"(INFO fila {draft['sheet_row']['info']}, "
             f"PLATAS 2026 fila {draft['sheet_row']['platas']}).")
    except Exception as exc:
        memory.log("order_sheet_written_notice_failed", client=client_id,
                   lead=draft.get("lead"), order_id=order_id, error=type(exc).__name__)


def handle_review_message(memory: Any, message: dict[str, str]) -> dict[str, Any]:
    """Act on one message from a review group; silent unless it quotes a known draft."""
    from . import whatsapp_web
    client_id = message.get("client") or ""
    out: dict[str, Any] = {"matched": True, "manual_review": True, "review_group": True}
    if not client_id:
        return out
    found = find_review_draft(memory, client_id, message.get("quoted_id", ""),
                              message.get("quoted_text", ""))
    if not found:
        return out
    draft_id, draft = found
    if not draft.get("quote"):
        # A paver order has no calculated quote: the team answers by hand.
        memory.log("review_paver_reply_ignored", client=client_id, lead=draft.get("lead"))
        return out

    text = (message.get("text") or "").strip()

    # --- FASE 2: escritura de pedidos (con el flag encendido manda sobre estos estados) ---
    status = draft.get("status")
    if POOLEDGE_WRITE_ORDERS and status in _PHASE2_STATUSES:
        if status == "final_published" and _is_confirm(text):
            _publish_preview(memory, whatsapp_web, client_id, draft_id, draft, message)
        elif (status in ("preview_sent", "sheet_writing", "sheet_written") and _is_ok(text)
              and (draft.get("preview") or status != "preview_sent")):
            _write_order(memory, whatsapp_web, client_id, draft_id, message)
        return out

    # --- FLUJO ORIGINAL: respuesta del dueño al presupuesto (Falta:/No cuadra:) ---
    try:
        issued = today()
        reading = read_owner_reply(text, draft, issued)
        plan = final_messages(draft, reading, memory.get_client_knowledge(client_id), issued)
        if not plan["messages"]:
            return out
        draft["partial"] = reading["partial"]
        sent = 0
        for position, t in enumerate(plan["messages"]):
            try:
                result = whatsapp_web.send_group_text(client_id, message["to_phone_id"],
                                                      message["chat_id"], t)
            except (RuntimeError, ValueError) as exc:
                # The bridge may answer 502 even though the message arrived: log, never
                # retry, and do not send the payment message without its budget.
                memory.log("review_group_send_uncertain", client=client_id,
                           lead=draft.get("lead"), error=str(exc)[:300])
                break
            sent += 1
            if not (plan["budget"] and position == 0) and not (
                    plan["payment"] and position == 1):
                link_followup(memory, client_id, draft_id, t, result)
            elif plan["payment"] and position == 0 and POOLEDGE_WRITE_ORDERS:
                # El dueño cita este presupuesto final para decir "confirmado".
                link_followup(memory, client_id, draft_id, t, result)
        budget_out = plan["budget"] and sent >= 1
        payment_out = plan["payment"] and sent == len(plan["messages"])
        if payment_out:
            draft["fields"] = _json_fields(reading["fields"])
            draft["status"] = "final_published"
            memory.log("final_budget_ready", client=client_id, lead=draft.get("lead"),
                       total=draft["quote"]["total"] + (reading["fields"]["shipping"] or 0))
        else:
            draft["status"] = "budget_sent" if budget_out else "needs_data"
        draft["last_reply_id"] = message.get("id")
    finally:
        memory.save()
    return out
