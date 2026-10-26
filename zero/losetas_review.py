"""LosetasChile: the owner's answer to a review draft becomes the final budget.

The review group holds the internal draft the agent published. The owner quotes
it with the missing data (shipping, dates, address...); this module reads that
answer and builds the two messages posted back in the SAME group, never to the
customer. Reading and composing are pure; only `handle_review_message` touches
memory and the bridge.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date as Date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .attention import fixed_answer
from .config import (LOSETASCHILE_DEPOSIT_CLP, REVIEW_DATE_ROLLOVER_DAYS, REVIEW_DRAFTS_KEPT,
                     REVIEW_MIN_SHIPPING_CLP, WHATSAPP_TIME_ZONE)
from .losetas_budget import format_customer_budget

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


def _plain(text: str) -> str:
    folded = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in folded if unicodedata.category(ch) != "Mn").casefold()


def text_key(text: str) -> str:
    """Hash of a draft's text, tolerant to the formatting WhatsApp may strip when quoting."""
    flat = " ".join(re.sub(r"[*_~]", "", text or "").split()).casefold()
    return hashlib.sha256(flat.encode("utf-8")).hexdigest()


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
    try:
        issued = today()
        reading = read_owner_reply(message.get("text", ""), draft, issued)
        plan = final_messages(draft, reading, memory.get_client_knowledge(client_id), issued)
        if not plan["messages"]:
            return out
        draft["partial"] = reading["partial"]
        sent = 0
        for position, text in enumerate(plan["messages"]):
            try:
                result = whatsapp_web.send_group_text(client_id, message["to_phone_id"],
                                                      message["chat_id"], text)
            except (RuntimeError, ValueError) as exc:
                # The bridge may answer 502 even though the message arrived: log, never
                # retry, and do not send the payment message without its budget.
                memory.log("review_group_send_uncertain", client=client_id,
                           lead=draft.get("lead"), error=str(exc)[:300])
                break
            sent += 1
            if not (plan["budget"] and position == 0) and not (
                    plan["payment"] and position == 1):
                link_followup(memory, client_id, draft_id, text, result)
        budget_out = plan["budget"] and sent >= 1
        payment_out = plan["payment"] and sent == len(plan["messages"])
        if payment_out:
            draft["status"] = "final_published"
            memory.log("final_budget_ready", client=client_id, lead=draft.get("lead"),
                       total=draft["quote"]["total"] + (reading["fields"]["shipping"] or 0))
        else:
            draft["status"] = "budget_sent" if budget_out else "needs_data"
        draft["last_reply_id"] = message.get("id")
    finally:
        memory.save()
    return out
