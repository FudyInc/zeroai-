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
from datetime import date as Date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .attention import fixed_answer
from . import config as _config
from .config import (LOSETASCHILE_DEPOSIT_CLP, LOSETASCHILE_PAVER_REVIEW_STATE_HOURS, REVIEW_DATE_ROLLOVER_DAYS, REVIEW_DRAFTS_KEPT,
                     REVIEW_MIN_SHIPPING_CLP, WHATSAPP_TIME_ZONE)
from .losetas_budget import format_customer_budget
from .losetas_color import COLOR_NAMES
from .losetas_polls import FACTORY_ADDRESS, PRODUCT_POLL_QUESTION, selected_category_from_history
from .losetas_text import plain
from .pool_border import POOL_PHOTO_REQUEST

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

EXTENSION_QUESTION = "¿La corrida adicional va alrededor de toda la piscina o solo en un lado?"
_EXTRA_ROW = re.compile(
    r"^(?:(?:quiero(?: agregar)?|agregar|agregue(?:le|me)?|anada(?:le|me)?) )?"
    r"(?:otra corrida|(?:una|1) corrida (?:mas|adicional))\b")
_ROW_SCOPE = re.compile(r"\b(?:lados?|alrededor|perimetro|completa|seccion|extremo|curva|irregular|romana)\b|^(?:todo|toda)$")


def _extension_request(message, history, review_status, draft_id):
    if "?" in message:
        return None
    value = plain(message)
    previous = next((t.get("text", "") for t in reversed(history) if t.get("role") == "agent"), "")
    followup = EXTENSION_QUESTION in previous and _ROW_SCOPE.search(value)
    if not followup:
        if not _EXTRA_ROW.match(value):
            return None
        if not ("bordes de piscina" in (review_status or "") or
                selected_category_from_history(history) == "bordes"):
            return None
    result = {"intent": "qualification", "flow_step": True}
    if draft_id and review_status:
        result["replaces_draft"] = draft_id
    if re.search(r"\b(?:curva|irregular|romana)\b", value):
        return {**result, "reply": POOL_PHOTO_REQUEST,
                "attention": "Revisar la foto o el croquis para calcular la extensión"}
    if _ROW_SCOPE.search(value):
        return {**result, "reply": "", "wait": True,
                "attention": "Revisar cobertura y cantidad de la extensión solicitada"}
    return {**result, "reply": EXTENSION_QUESTION}


_PAYMENT_REPORT = re.compile(
    r"(?:(?:si|listo|gracias) )?(?:ya )?(?:transferi|abone|pague|hice la transferencia)"
    r"(?: (?:el abono|las diez lucas|los diez mil|(?:los )?\d+(?: \d{3})*(?: pesos| mil| lucas)?))?")
_COLOR_CHOICE = "|".join(COLOR_NAMES)
_CORRECTION = re.compile(rf"(?:mejor |prefiero |cambielo a )?(?:(?P<color>{_COLOR_CHOICE})(?: y )?)?"
                         r"(?P<pickup>lo retiro yo|retiro en fabrica|paso a retirar|lo paso a retirar)?")


def _current_order_notice(at, history):
    """A notice may attach to the next draft only while the same order is open."""
    try:
        notice = datetime.fromisoformat(at)
        if not timedelta() <= datetime.now(timezone.utc) - notice <= timedelta(hours=LOSETASCHILE_PAVER_REVIEW_STATE_HOURS):
            return False
        for turn in reversed(history):
            if turn.get("role") == "agent" and PRODUCT_POLL_QUESTION in str(turn.get("text") or ""):
                return notice >= datetime.fromisoformat(turn.get("at"))
        return True
    except (TypeError, ValueError):
        return False


def customer_review_change(memory, client_id, lead, message, history, review_status):
    """Draft a response to a specific order change, without mutating stored state."""
    notes = memory.lead_notes(client_id, lead).get("budget_review") or {}
    drafts = memory.clients.get(client_id, {}).get("review_drafts", {})
    draft_id = notes.get("draft_id")
    if notes.get("at") and not _current_order_notice(notes["at"], history or memory.get_conversation(client_id, lead)):
        draft_id, review_status = None, None
    if not draft_id and review_status:  # Older review notes lack the group message ID.
        candidates = [k for k, d in drafts.items() if d.get("lead") == lead and
                      d.get("status") in ("pending", "needs_data", "budget_sent", "final_published")]
        if len(candidates) == 1:
            draft_id = candidates[0]
    draft = drafts.get(draft_id, {})
    if draft.get("lead") != lead or draft.get("status") == "superseded":
        draft_id, draft = None, {}
    value = plain(message)
    if not any(q in message for q in "¿?") and _PAYMENT_REPORT.fullmatch(value):
        unassigned_lead = None
        if not draft_id and not review_status and lead:
            turns = history or memory.get_conversation(client_id, lead)
            if selected_category_from_history(turns):
                unassigned_lead = lead
        return {"reply": "Gracias por avisar. El equipo va a verificar su abono.",
                "intent": "info", "flow_step": True, "reported_draft": draft_id,
                "unassigned_deposit_lead": unassigned_lead,
                "attention": "Verificar el abono informado por el cliente"}
    extension = _extension_request(message, history, review_status, draft_id)
    if extension:
        return extension
    if review_status and draft and "?" not in message:
        change = _CORRECTION.fullmatch(value)
        if change and (change["color"] or change["pickup"]) and draft.get("quote"):
            quote = dict(draft["quote"])
            if change["pickup"]:
                quote["delivery_detail"] = f"Retiro en fábrica: {FACTORY_ADDRESS}"
            color = change["color"] or draft.get("color")
            if color == draft.get("color") and quote == draft["quote"]:
                return {"reply": "", "intent": "pricing", "wait": True}
            result = {"reply": "", "intent": "pricing", "quote": quote,
                      "selected_tone": color, "replaces_draft": draft_id}
            if draft.get("paver_order"):
                result.update(quote=None, paver_order=dict(draft["paver_order"], color=color,
                              delivery_detail=quote.get("delivery_detail")))
            return result
        if (re.match(r"^(?:mejor|prefiero|cambie(?:lo|me)?|cambiar|agregue|quiero cambiar)\b", value)
                and re.search(r"\b(?:modelo|color|retiro|despacho|formato|cantidad|piezas?|bordes?|"
                              rf"pastelon(?:es)?|corridas?|{_COLOR_CHOICE}|\d+)\b", value)):
            return {"reply": "", "intent": "pricing", "wait": True, "replaces_draft": draft_id,
                    "attention": "Actualizar y revisar el pedido antes de emitir el presupuesto"}
    return None


def record_review_change(memory, client_id, change):
    drafts = memory.clients.get(client_id, {}).get("review_drafts", {})
    replaced = drafts.get(change.get("replaces_draft"))
    if replaced:
        replaced["status"] = "superseded"
    reported = drafts.get(change.get("reported_draft"))
    if reported:
        reported["deposit_reported"] = True
    unassigned = change.get("unassigned_deposit_lead")
    if unassigned:
        memory.set_lead_note(client_id, unassigned, "unassigned_deposit", {"at": datetime.now(timezone.utc).isoformat()})
    if replaced or reported or unassigned:
        memory.save()
    return replaced


def store_review_draft(memory: Any, client_id: str, group_message_id: str,
                       draft: dict[str, Any]) -> None:
    """Remember a published draft by group message id and by text hash; keep the last N."""
    bucket = memory.clients.setdefault(client_id, {})
    drafts = bucket.setdefault("review_drafts", {})
    index = bucket.setdefault("review_draft_index", {})
    drafts[group_message_id] = dict(draft, status="pending")
    lead = draft.get("lead")
    notice = memory.lead_notes(client_id, lead).get("unassigned_deposit") if lead else None
    if notice:
        if _current_order_notice(notice.get("at"), memory.get_conversation(client_id, lead)):
            drafts[group_message_id]["deposit_reported"] = True
        memory.set_lead_note(client_id, lead, "unassigned_deposit", None)
    index[text_key(draft.get("text", ""))] = group_message_id
    while len(drafts) > REVIEW_DRAFTS_KEPT:
        drafts.pop(next(iter(drafts)))
    for key in [k for k, v in index.items() if v not in drafts]:
        del index[key]


def _stanza(message_id: str) -> str:
    """The WhatsApp stanza id inside `<fromMe>_<chat>_<stanza>[_<author>]`.

    When the bridge cannot load the quoted message it rebuilds the id as
    `false_<chat>_<stanza>`, while the draft was stored as `true_<chat>_<stanza>_<author>`:
    only the stanza is shared by both forms."""
    parts = str(message_id or "").split("_")
    return parts[2] if len(parts) >= 3 and parts[0] in ("true", "false") else ""


def find_review_draft(memory: Any, client_id: str, quoted_id: str,
                      quoted_text: str) -> tuple[str, dict[str, Any]] | None:
    bucket = memory.clients.get(client_id, {})
    drafts = bucket.get("review_drafts") or {}
    index = bucket.get("review_draft_index") or {}
    if quoted_id and quoted_id in drafts:
        return quoted_id, drafts[quoted_id]
    linked = index.get(quoted_id) if quoted_id else None
    if linked in drafts:
        return linked, drafts[linked]
    stanza = _stanza(quoted_id)
    if stanza:
        for key in [*drafts, *index]:
            target = key if key in drafts else index[key]
            if _stanza(key) == stanza and target in drafts:
                return target, drafts[target]
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
    told = re.match(r"Despacho:\s*(.+)$", detail)
    if not fields["pickup"] and not fields["address"] and told:
        # Lo que el cliente dio en el chat: dirección escrita o su ubicación de WhatsApp.
        place = told.group(1).strip()
        link = _URL.search(place)
        if link:
            fields["map_url"] = fields["map_url"] or link.group(0)
            fields["address"] = _URL.sub(" ", place).strip(" ,;") or "Ubicación compartida por el cliente"
        else:
            fields["address"] = place
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
        delivery=fields["delivery"], deposit=None if draft.get("deposit_reported") else LOSETASCHILE_DEPOSIT_CLP,
        map_url=fields["map_url"], pickup=fields["pickup"])
    if budget is None:
        early = any(day < issued for day in fields["delivery"])
        return only("No cuadra: " + ("fecha anterior a la emisión" if early else
                                     "cifras o datos del presupuesto no son consistentes"))
    total = quote["total"] + (fields["shipping"] or 0)
    if draft.get("deposit_reported"):
        amount = draft.get("confirmed_deposit")
        if amount is not None:
            if amount > total:
                return only("Revisar el total y el abono confirmado.")
            budget += f"\nAbono confirmado: {_money(amount)}. Saldo: {_money(total - amount)}."
        return {"messages": [budget], "budget": True, "payment": False}
    bank = bank_block(knowledge)
    if not bank:
        return {"messages": [budget, "Falta en la ficha: datos de transferencia"],
                "budget": True, "payment": False}
    payment = (f"Para confirmar su pedido se hace un abono de {_money(LOSETASCHILE_DEPOSIT_CLP)} "
               f"y el resto ({_money(total - LOSETASCHILE_DEPOSIT_CLP)}) se paga contra entrega, "
               f"en efectivo o por transferencia.\n\nDatos para la transferencia:\n{bank}\n\n"
               "Cuando haga el abono, envíenos el comprobante por este chat.")
    return {"messages": [budget, payment], "budget": True, "payment": True}


_APPROVAL = re.compile(r"^\s*(ok[aeiy]*|okey|listo|dale|aprobado|apruebo|s[ií]|va|enviar|"
                       r"\U0001F44D[\U0001F3FB-\U0001F3FF]?|\u2705)\s*[.!]*\s*$", re.I)


def is_approval(text: str) -> bool:
    """A bare "ok" (or 👍) on a draft: an approval that carries none of the data."""
    return bool(_APPROVAL.match(text or ""))


def approval_hint(reading: dict[str, Any]) -> str:
    """What a bare approval still needs, with the format the reader understands."""
    missing = reading["missing"] or ["fecha"]
    example = ["Despacho $15.000 a Puente Alto", "Dirección: Calle 123, Puente Alto",
               "Fecha: 20/11"] if "despacho" in missing else ["Fecha: 20/11"]
    return (f"Para armar el presupuesto final falta: {', '.join(missing)}.\n"
            "Responde citando el borrador, por ejemplo:\n" + "\n".join(example) +
            ("\n(o «Retiro» si lo retira en fábrica)" if "despacho" in missing else ""))


# --- the one entry point that touches memory and the bridge ------------------

def _send_to_customer(memory: Any, client_id: str, draft: dict[str, Any],
                      texts: list[str]) -> int:
    """Send the reviewed budget (and payment message) to the customer's chat.

    Returns how many messages went out, in order; stops at the first failure so the
    payment message never leaves without its budget."""
    from . import whatsapp_web
    phone = re.sub(r"\D", "", draft.get("phone") or "")
    chat_id = str(draft.get("chat_id") or "")
    if not (8 <= len(phone) <= 15 and re.fullmatch(r"\d{8,20}@(c\.us|lid)", chat_id)):
        return 0
    sent = 0
    for text in texts:
        try:
            result = whatsapp_web.bridge_request(
                "/send", {"to": phone, "text": text, "chat_id": chat_id, "typing_ms": 1500},
                client_id=client_id)
        except (RuntimeError, ValueError) as exc:
            memory.log("reviewed_budget_send_failed", client=client_id, lead=draft.get("lead"),
                       error=str(exc)[:300])
            break
        if not result.get("id") or result.get("ack") == -1:
            break
        sent += 1
        if draft.get("lead"):
            memory.add_turn(client_id, draft["lead"], "agent", text)
    return sent



def handle_review_message(memory: Any, message: dict[str, str]) -> dict[str, Any]:
    """Act on one message from a review group; silent unless it quotes a known draft."""
    from . import whatsapp_web
    client_id = message.get("client") or ""
    out: dict[str, Any] = {"matched": True, "manual_review": True, "review_group": True}
    if not client_id:
        return out
    found = find_review_draft(memory, client_id, message.get("quoted_id", ""),
                              message.get("quoted_text", ""))
    confirmation = re.fullmatch(r"abono confirmado\s+\$?([1-9]\d{0,2}(?:\.\d{3}){1,3}|[1-9]\d{0,11})",
                                message.get("text", "").strip(), re.I)
    if not found and confirmation and message.get("quoted_id"):
        quoted = message["quoted_id"]
        for key, item in memory.clients.get(client_id, {}).get("review_drafts", {}).items():
            published = item.get("final_message_id")
            if published and (published == quoted or (_stanza(quoted) and _stanza(quoted) == _stanza(published))):
                found = key, item
                break
    if not found:
        return out
    draft_id, draft = found
    if draft.get("status") == "superseded":
        return out
    if confirmation:
        if not draft.get("deposit_reported") or draft.get("confirmed_deposit") is not None:
            return out
        amount = int(confirmation[1].replace(".", ""))
        total = draft.get("reviewed_total")
        # Before freight is reviewed, a deposit within the product subtotal is unambiguous.
        ceiling = total if total is not None else (draft.get("quote") or {}).get("total")
        if ceiling is None or amount > ceiling:
            acknowledgment = "Revise el total del presupuesto antes de confirmar el abono."
        else:
            draft["confirmed_deposit"] = amount
            memory.save()
            acknowledgment = f"Abono confirmado: {_money(amount)}."
            if total is not None:
                acknowledgment += f" Saldo: {_money(total - amount)}."
        try:
            whatsapp_web.send_group_text(client_id, message["to_phone_id"], message["chat_id"], acknowledgment)
        except (RuntimeError, ValueError) as exc:
            memory.log("review_group_send_uncertain", client=client_id, lead=draft.get("lead"),
                       error=str(exc)[:300])
            memory.save()
        return out
    if not draft.get("quote") and draft.get("order") == "pastelones":
        # Drafts published before paver drafts carried a quote: rebuilt from the
        # one line the code wrote, only when its figures add up.
        from .losetas_budget import paver_quote_from_draft
        draft["quote"] = paver_quote_from_draft(draft.get("text", ""))
    if not draft.get("quote"):
        # No calculated quote (price or yield unknown): the team answers by hand.
        memory.log("review_paver_reply_ignored", client=client_id, lead=draft.get("lead"))
        return out
    try:
        issued = today()
        reading = read_owner_reply(message.get("text", ""), draft, issued)
        plan = final_messages(draft, reading, memory.get_client_knowledge(client_id), issued)
        if not plan["messages"] and is_approval(message.get("text", "")):
            plan = {"messages": [approval_hint(reading)], "budget": False, "payment": False}
        if not plan["messages"]:
            return out
        draft["partial"] = reading["partial"]
        if _config.LOSETASCHILE_AUTO_SEND_REVIEWED_BUDGET and plan["budget"] and draft.get("chat_id"):
            # Diego respondió con los datos: esa es la revisión. Sale al cliente, y en el
            # grupo queda el aviso; si algo falla, los mensajes quedan aquí para él.
            delivered = _send_to_customer(memory, client_id, draft, plan["messages"])
            total = draft["quote"]["total"] + (reading["fields"]["shipping"] or 0)
            if delivered == len(plan["messages"]):
                notice = (f"✅ Enviado al cliente +{draft.get('phone')}: presupuesto final por "
                          f"{_money(total)}" + (" y datos de abono." if plan["payment"] else "."))
                plan = {"messages": [notice], "budget": False, "payment": False,
                        "delivered_budget": True, "delivered_payment": plan["payment"]}
            else:
                lead_in = ("⚠️ No se pudo enviar al cliente; revisa su chat antes de mandarlo tú."
                           if not delivered else
                           f"⚠️ Al cliente le llegó solo el presupuesto; falta el mensaje de abono:")
                plan = dict(plan, messages=[lead_in, *plan["messages"][delivered:]],
                            delivered_budget=delivered >= 1, delivered_payment=False)
                if delivered:
                    plan["budget"] = False
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
            if (plan["budget"] and position == 0) or (plan.get("delivered_budget") and position == 0):
                draft["final_message_id"] = result.get("id")
            if not (plan["budget"] and position == 0) and not (
                    plan["payment"] and position == 1):
                link_followup(memory, client_id, draft_id, text, result)
        budget_out = (plan["budget"] and sent >= 1) or plan.get("delivered_budget", False)
        payment_out = (plan["payment"] and sent == len(plan["messages"])) or \
            plan.get("delivered_payment", False)
        if budget_out:
            draft["reviewed_total"] = draft["quote"]["total"] + (reading["fields"]["shipping"] or 0)
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
