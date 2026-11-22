"""Onboarding por archivo: catálogo y preguntas frecuentes de una empresa nueva.

La empresa sube UN archivo (CSV o XLSX) y su agente de WhatsApp queda con base de
conocimiento. Nada de almacén paralelo: lo importado termina donde el agente ya lee.

- Catálogo -> `set_client_pricing` (lo que usa el cotizador determinista,
  orchestrator `compute_quote(extract_request(...))`) Y una sección de la ficha,
  porque el modelo solo ve la ficha: la lista de precios no viaja en su prompt.
- FAQ -> otra sección de la ficha.

Cada sección va entre marcadores (`<!-- catalogo:inicio -->` ... `<!-- catalogo:fin -->`)
y cada importación regenera SOLO la suya. El texto escrito a mano no se toca: lo
que está fuera de los marcadores se copia byte a byte.

Solo stdlib: CSV con `csv`, XLSX con `zipfile` + `xml.etree`. La política (techos,
columnas, clientes bloqueados) vive en config.py.
"""
from __future__ import annotations

import csv
import io
import math
import re
import secrets
import threading
import time
import unicodedata
import zipfile
import zlib
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree

from .config import (ONBOARDING_CHECKLIST_REQUIRED, ONBOARDING_COLUMNS, ONBOARDING_MAX_COLUMNS,
                     ONBOARDING_MAX_ROWS, ONBOARDING_MAX_PREVIEWS,
                     ONBOARDING_MAX_PREVIEWS_PER_CLIENT,
                     ONBOARDING_PREVIEW_TTL_S, ONBOARDING_REQUIRED_COLUMNS,
                     ONBOARDING_XLSX_MAX_EXPANDED_BYTES)
from .quotes import normalize_pricing

KINDS = tuple(ONBOARDING_COLUMNS)
SECTION_TITLES = {"catalogo": "## Catálogo y precios", "faq": "## Preguntas frecuentes"}


class OnboardingError(Exception):
    """Falla que el endpoint devuelve tal cual: `status` HTTP y motivo legible."""

    def __init__(self, status: int, motivo: str):
        super().__init__(motivo)
        self.status = status
        self.motivo = motivo


def _check_kind(kind: str) -> None:
    if kind not in KINDS:
        raise OnboardingError(400, f"tipo desconocido «{kind}»; usa uno de: {', '.join(KINDS)}")


def template_csv(kind: str) -> str:
    """La plantilla: solo los encabezados, en el orden de config."""
    _check_kind(kind)
    return ",".join(ONBOARDING_COLUMNS[kind]) + "\r\n"


# --- lectura del archivo --------------------------------------------------------

def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(text))
                   if not unicodedata.combining(c))


def _header_key(value: Any) -> str:
    return re.sub(r"\s+", "_", _fold(str(value or "")).strip().lower())


def _decode(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("latin-1")


Table = List[Tuple[int, List[Any]]]


def _read_csv(content: bytes) -> Table:
    text = _decode(content)
    stream = io.StringIO(text, newline="")
    first = next((line for line in stream if line.strip()), "")
    stream.seek(0)
    # Los encabezados nunca llevan coma ni punto y coma: contarlos en la primera
    # línea decide sin ambigüedad. Sniffer solo desempata (archivo de una columna),
    # porque en las filas «12.990,00» confunde a cualquier heurística.
    if first.count(";") != first.count(","):
        delimiter = ";" if first.count(";") > first.count(",") else ","
    else:
        try:
            delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;").delimiter
        except csv.Error:
            delimiter = ","
    rows: Table = []
    for n, cells in enumerate(csv.reader(stream, delimiter=delimiter, strict=True), start=1):
        if any(cell.strip() for cell in cells):
            if len(rows) >= ONBOARDING_MAX_ROWS + 1:
                raise OnboardingError(413, f"el archivo trae más de {ONBOARDING_MAX_ROWS} filas")
            rows.append((n, cells))
    return rows


_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
       "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}


def _xml(zf: zipfile.ZipFile, name: str) -> ElementTree.Element:
    data = zf.read(name)
    # Un XLSX real nunca declara DTD ni entidades; uno que las trae es un archivo
    # armado para inflar memoria (billion laughs). Se rechaza antes de parsear.
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise OnboardingError(422, "el XLSX trae declaraciones XML no permitidas")
    return ElementTree.fromstring(data)


def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref or "")
    if not letters:
        return -1
    n = 0
    for ch in letters.group(0):
        n = n * 26 + (ord(ch) - 64)
        if n > ONBOARDING_MAX_COLUMNS:
            return ONBOARDING_MAX_COLUMNS
    return n - 1


def _number(text: str) -> Any:
    try:
        value = Decimal(text)
    except InvalidOperation:
        return text
    # Excel guarda números como texto decimal. Convertirlos primero a float
    # redondearía el precio antes de que se pueda validar la cifra original.
    if value.is_finite() and value.adjusted() <= 308 and value == value.to_integral_value():
        return int(value)
    return value


def _xlsx_text(node: ElementTree.Element) -> str:
    parts = node.findall("m:t", _NS) + node.findall("m:r/m:t", _NS)
    return "".join(t.text or "" for t in parts)


def _read_xlsx(content: bytes) -> Table:
    """Primera hoja del libro. Celdas con fórmula: su último valor calculado (el
    que Excel guardó), nunca se evalúa nada. Celdas numéricas llegan como número."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise OnboardingError(422, "el archivo no es un XLSX válido")
    with zf:
        if sum(info.file_size for info in zf.infolist()) > ONBOARDING_XLSX_MAX_EXPANDED_BYTES:
            raise OnboardingError(413, "el XLSX descomprimido supera el tamaño permitido")
        names = set(zf.namelist())
        try:
            book = _xml(zf, "xl/workbook.xml")
        except KeyError:
            raise OnboardingError(422, "el archivo no es un XLSX válido (falta el libro)")
        sheet = book.find("m:sheets/m:sheet", _NS)
        if sheet is None:
            raise OnboardingError(422, "el XLSX no tiene hojas")
        target = "xl/worksheets/sheet1.xml"
        rid = sheet.get(f"{{{_NS['r']}}}id")
        if "xl/_rels/workbook.xml.rels" in names and rid:
            for rel in _xml(zf, "xl/_rels/workbook.xml.rels").findall("rel:Relationship", _NS):
                if rel.get("Id") == rid:
                    ref = rel.get("Target") or ""
                    target = ref.lstrip("/") if ref.startswith("/") else "xl/" + ref
                    break
        if target not in names:
            raise OnboardingError(422, "el XLSX no trae la primera hoja")
        shared: List[str] = []
        if "xl/sharedStrings.xml" in names:
            for si in _xml(zf, "xl/sharedStrings.xml").findall("m:si", _NS):
                shared.append(_xlsx_text(si))
        rows: Table = []
        row_number = 0
        for row in _xml(zf, target).iter(f"{{{_NS['m']}}}row"):
            try:
                next_number = int(row.get("r", row_number + 1))
            except ValueError:
                raise OnboardingError(422, "el XLSX tiene un número de fila ilegible")
            if next_number <= row_number:
                raise OnboardingError(422, "el XLSX tiene filas fuera de orden")
            row_number = next_number
            if len(rows) > ONBOARDING_MAX_ROWS + 1:
                raise OnboardingError(413, f"el archivo trae más de {ONBOARDING_MAX_ROWS} filas")
            values: Dict[int, Any] = {}
            for pos, cell in enumerate(row.findall("m:c", _NS)):
                idx = _col_index(cell.get("r") or "")
                idx = pos if idx < 0 else idx
                if idx >= ONBOARDING_MAX_COLUMNS:
                    continue   # fuera de cualquier plantilla: no se lee
                kind = cell.get("t")
                v = cell.find("m:v", _NS)
                raw = v.text if v is not None else None
                if kind == "s":
                    try:
                        value: Any = shared[int(raw)]
                    except (TypeError, ValueError, IndexError):
                        value = ""
                elif kind == "inlineStr":
                    inline = cell.find("m:is", _NS)
                    value = _xlsx_text(inline) if inline is not None else ""
                elif kind in ("str", "e"):
                    value = raw or ""
                elif kind == "b":
                    value = "VERDADERO" if raw == "1" else "FALSO"
                else:
                    value = _number(raw) if raw is not None else ""
                values[idx] = value
            if values:
                rows.append((row_number, [values.get(i, "") for i in range(max(values) + 1)]))
        return rows


def read_table(filename: str, content: bytes) -> Table:
    """Filas con su número en la planilla. CSV o XLSX según el contenido."""
    if not content or not content.strip():
        raise OnboardingError(422, "el archivo está vacío")
    name = (filename or "").lower()
    if content[:4] == b"PK\x03\x04":
        return _read_xlsx(content)
    if content[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" or name.endswith(".xls"):
        raise OnboardingError(415, "formato .xls antiguo no soportado: guárdalo como .xlsx o .csv")
    if name.endswith(".xlsx"):
        raise OnboardingError(422, "el archivo dice ser .xlsx pero no lo es")
    return _read_csv(content)


# --- validación -----------------------------------------------------------------

def parse_clp(value: Any) -> int:
    """Precio en pesos chilenos enteros. Acepta `$12.990`, `12990`, `12.990,00`,
    `12,990` y números de Excel. Lo ilegible levanta ValueError: nunca se
    convierte en 0, porque un 0 cotizado es peor que un precio faltante."""
    if isinstance(value, bool):
        raise ValueError("precio ilegible")
    if isinstance(value, (float, Decimal)):
        if not math.isfinite(value):
            raise ValueError("precio ilegible")
    if isinstance(value, (int, float, Decimal)):
        if value != int(value):
            raise ValueError("el precio en pesos no lleva decimales")
        number = int(value)
    else:
        text = re.sub(r"(?i)\s|\$|clp|pesos?", "", str(value or ""))
        if not text:
            raise ValueError("falta el precio")
        if not re.fullmatch(r"[0-9](?:[0-9.,]*[0-9])?", text):
            raise ValueError("precio ilegible")
        dot, comma = text.rfind("."), text.rfind(",")
        if dot >= 0 and comma >= 0:            # el último separador es el decimal
            decimal = "," if comma > dot else "."
            entero, _, frac = text.rpartition(decimal)
            miles = "." if decimal == "," else ","
            if not re.fullmatch(r"\d{1,3}(?:" + re.escape(miles) + r"\d{3})*", entero):
                raise ValueError("precio ilegible")
            entero = entero.replace(miles, "")
        elif dot >= 0 or comma >= 0:
            sep = "." if dot >= 0 else ","
            if re.fullmatch(r"\d{1,3}(?:" + re.escape(sep) + r"\d{3})+", text):
                entero, frac = text.replace(sep, ""), ""
            elif text.count(sep) == 1:
                entero, frac = text.split(sep)
            else:
                raise ValueError("precio ilegible")
        else:
            entero, frac = text, ""
        if not entero.isdigit() or (frac and not frac.isdigit()):
            raise ValueError("precio ilegible")
        if frac.strip("0"):
            raise ValueError("el precio en pesos no lleva decimales")
        number = int(entero)
    if number <= 0:
        raise ValueError("el precio debe ser mayor que 0")
    try:
        exacto = float(number) == number
    except OverflowError:
        exacto = False
    if not exacto:
        raise ValueError("el cotizador no puede representar ese precio en pesos exactos")
    return number


def _cell(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return " ".join(str(value if value is not None else "").split())


def _key(text: str) -> str:
    return " ".join(_fold(text).casefold().split())


def _catalog_id(row: Dict[str, Any]) -> str:
    """El mismo id que pondrá normalize_pricing: sku si viene, si no el nombre."""
    return normalize_pricing({"items": [{"id": row.get("sku") or row["nombre"],
                                         "name": row["nombre"], "unit_price": 1}]}
                             )["items"][0]["id"]


def validate(kind: str, table: Table) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Filas válidas y errores con el número de fila que ve quien abre la planilla."""
    _check_kind(kind)
    rows = ((n, r) for n, r in table if any(_cell(c) for c in r))
    header = next(rows, None)
    if header is None:
        raise OnboardingError(422, "el archivo está vacío")
    header_number, cells = header
    headers = [_header_key(h) for h in cells]
    errors: List[Dict[str, Any]] = []
    for col in ONBOARDING_REQUIRED_COLUMNS[kind]:
        if col not in headers:
            errors.append({"fila": header_number, "columna": col, "motivo": "falta la columna obligatoria"})
    if errors:
        return [], errors
    index = {col: headers.index(col) for col in ONBOARDING_COLUMNS[kind] if col in headers}
    data = list(rows)
    if len(data) > ONBOARDING_MAX_ROWS:
        raise OnboardingError(413, f"el archivo trae {len(data)} filas; el máximo es "
                                   f"{ONBOARDING_MAX_ROWS}")
    valid: List[Dict[str, Any]] = []
    seen: Dict[str, int] = {}
    for fila, raw in data:
        def get(col: str) -> Any:
            i = index.get(col)
            return raw[i] if i is not None and i < len(raw) else ""
        row: Dict[str, Any] = {"fila": fila}
        row_errors = []
        for col in ONBOARDING_COLUMNS[kind]:
            row[col] = _cell(get(col))
            if "<!--" in row[col]:
                row_errors.append({"fila": fila, "columna": col,
                                   "motivo": "el texto contiene la secuencia reservada <!--"})
        # Más celdas que encabezados: casi siempre una coma sin comillas dentro de
        # un texto. Tomar las primeras columnas truncaría la respuesta en silencio.
        if any(_cell(c) for c in raw[len(headers):]):
            row_errors.append({"fila": fila, "columna": headers[-1] or "?",
                               "motivo": "la fila trae más columnas que el encabezado; "
                                         "pon entre comillas el texto que lleva comas"})
        for col in ONBOARDING_REQUIRED_COLUMNS[kind]:
            if col != "precio" and not row[col]:
                row_errors.append({"fila": fila, "columna": col, "motivo": "vacío"})
        if kind == "catalogo":
            try:
                row["precio"] = parse_clp(get("precio"))
            except ValueError as e:
                row_errors.append({"fila": fila, "columna": "precio", "motivo": str(e)})
        if not row_errors:
            key = _catalog_id(row) if kind == "catalogo" else _key(row["pregunta"])
            if key in seen:
                col = ("sku" if row.get("sku") else "nombre") if kind == "catalogo" else "pregunta"
                row_errors.append({"fila": fila, "columna": col,
                                   "motivo": f"repetido: ya está en la fila {seen[key]}"})
            else:
                seen[key] = fila
        if row_errors:
            errors.extend(row_errors)
        else:
            valid.append(row)
    return valid, errors


# --- la sección de la ficha -----------------------------------------------------

def markers(kind: str) -> Tuple[str, str]:
    return f"<!-- {kind}:inicio -->", f"<!-- {kind}:fin -->"


def _clp(n: int) -> str:
    return "$" + f"{n:,}".replace(",", ".")


def render_section(kind: str, rows: List[Dict[str, Any]]) -> str:
    """El bloque completo, marcadores incluidos. Un ítem por línea de lista: así
    `select_knowledge` (whatsapp_context.py) recorta ítem por ítem, cada uno con
    el título de la sección delante."""
    start, end = markers(kind)
    lines = []
    for r in rows:
        if kind == "catalogo":
            line = f"- {r['nombre']}: precio {_clp(r['precio'])}"
            line += f" por {r['unidad']}." if r.get("unidad") else "."
            for label, col in (("Categoría", "categoria"), ("SKU", "sku")):
                if r.get(col):
                    line += f" {label}: {r[col]}."
            if r.get("descripcion"):
                line += " " + r["descripcion"].rstrip(".") + "."
            if r.get("stock"):
                line += f" Stock: {r['stock']}."
        else:
            line = f"- {r['pregunta']}\n  {r['respuesta']}"
        lines.append(line)
    return f"{start}\n\n{SECTION_TITLES[kind]}\n\n" + "\n".join(lines) + f"\n\n{end}"


def _span(knowledge: str, kind: str) -> Optional[Tuple[int, int]]:
    """(inicio, fin) del bloque con sus marcadores; None si no existe. Marcadores
    repetidos, sueltos o invertidos: error — no se adivina qué borrar."""
    start, end = markers(kind)
    a, b = knowledge.count(start), knowledge.count(end)
    if a == 0 and b == 0:
        return None
    s, e = knowledge.find(start), knowledge.find(end)
    if a != 1 or b != 1 or e < s:
        raise OnboardingError(409, f"la ficha tiene los marcadores de «{kind}» dañados "
                                   f"({start} / {end}); corrígelos a mano antes de importar")
    return s, e + len(end)


def _validate_sections(knowledge: str) -> None:
    spans = sorted(span for kind in KINDS if (span := _span(knowledge, kind)))
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        raise OnboardingError(409, "las secciones de catálogo y FAQ se superponen en la ficha")


def replace_section(knowledge: str, kind: str, block: str) -> str:
    """La ficha con SOLO la sección `kind` regenerada. Lo de afuera, intacto. Si la
    sección no existía, va al final: el comienzo de la ficha es lo que
    `select_knowledge` conserva siempre como presentación del negocio."""
    knowledge = knowledge or ""
    _validate_sections(knowledge)
    span = _span(knowledge, kind)
    if span is None:
        return knowledge + "\n\n" + block if knowledge else block
    return knowledge[:span[0]] + block + knowledge[span[1]:]


def section_text(knowledge: str, kind: str) -> str:
    span = _span(knowledge or "", kind)
    return knowledge[span[0]:span[1]] if span else ""


def manual_text(knowledge: str) -> str:
    """La ficha sin las secciones generadas: lo escrito a mano."""
    text = knowledge or ""
    _validate_sections(text)
    for kind in KINDS:
        span = _span(text, kind)
        if span:
            text = text[:span[0]] + text[span[1]:]
    return text.strip()


def faq_entries(knowledge: str) -> Dict[str, str]:
    """{pregunta normalizada: respuesta} de la sección FAQ vigente."""
    body = section_text(knowledge, "faq")
    body = body.rpartition(markers("faq")[1])[0] if body else ""
    out: Dict[str, str] = {}
    for entry in re.split(r"\n(?=- )", body):
        if not entry.startswith("- "):
            continue
        first, _, rest = entry[2:].partition("\n")
        out[_key(first)] = " ".join(rest.split())
    return out


# --- vista previa y aplicación --------------------------------------------------

def pricing_items(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"id": r.get("sku") or r["nombre"], "name": r["nombre"],
             "unit_price": r["precio"], "unit": r.get("unidad") or None} for r in rows]


def summarize(kind: str, rows: List[Dict[str, Any]], errors: List[Dict[str, Any]],
              knowledge: str, pricing: Dict[str, Any]) -> Dict[str, int]:
    """Cuántas filas son nuevas, cambian o quedan igual frente a lo vigente. El
    catálogo se compara con la lista de precios (lo que cotiza); la FAQ, con su
    sección de la ficha. `se_eliminan`: lo vigente que el archivo ya no trae."""
    if kind == "catalogo":
        before = {it["id"]: (it["name"], float(it["unit_price"]), it.get("unit"))
                  for it in normalize_pricing(pricing).get("items", [])}
        after = {it["id"]: (it["name"], float(it["unit_price"]), it.get("unit"))
                 for it in normalize_pricing({"items": pricing_items(rows)})["items"]}
    else:
        before = faq_entries(knowledge)
        after = {_key(r["pregunta"]): r["respuesta"] for r in rows}
    nuevas = sum(1 for k in after if k not in before)
    sin_cambio = sum(1 for k, v in after.items() if k in before and before[k] == v)
    filas_con_error = len({e["fila"] for e in errors})
    return {"validas": len(rows), "con_error": filas_con_error, "nuevas": nuevas,
            "cambian": len(after) - nuevas - sin_cambio, "sin_cambio": sin_cambio,
            "se_eliminan": sum(1 for k in before if k not in after)}


def preview(kind: str, filename: str, content: bytes, knowledge: str,
            pricing: Dict[str, Any]) -> Dict[str, Any]:
    """Lee y valida; no escribe nada. Sin token si hay errores o nada válido:
    aplicar la parte buena de un catálogo con filas rotas borraría de la lista
    de precios los productos de esas filas sin que nadie lo note."""
    _check_kind(kind)
    _validate_sections(knowledge or "")
    try:
        table = read_table(filename, content)
    except (ElementTree.ParseError, csv.Error, zipfile.BadZipFile, RuntimeError,
            NotImplementedError, zlib.error, EOFError) as e:
        raise OnboardingError(422, f"no se pudo leer el archivo ({type(e).__name__})")
    rows, errors = validate(kind, table)
    return {"rows": rows, "errors": errors,
            "summary": summarize(kind, rows, errors, knowledge, pricing)}


def apply_rows(memory: Any, client: str, kind: str, rows: List[Dict[str, Any]],
               motivo: str, price_normalizer=normalize_pricing) -> Dict[str, Any]:
    """Escribe la importación: la sección de la ficha (versión nueva, con
    rollback) y, si es catálogo, la lista de precios. La ficha se regenera sobre
    la vigente AHORA, no sobre la de la vista previa: una edición manual hecha
    entre medio no se pierde. No guarda a disco: eso es de quien llama."""
    actual = memory.get_client_knowledge(client)
    nueva = replace_section(actual, kind, render_section(kind, rows))
    pricing = None
    if kind == "catalogo":
        previo = memory.get_client_pricing(client) or {}
        pricing = price_normalizer({"currency": "CLP", "iva_rate": previo.get("iva_rate"),
                                    "items": pricing_items(rows)})
        memory.set_client_pricing(client, pricing)
    entrada = memory.set_client_knowledge(client, nueva, motivo=motivo)
    return {"version": entrada["version"], "chars": entrada["chars"],
            "aplicadas": len(rows),
            "pricing_items": len(pricing["items"]) if pricing else None}


class PreviewStore:
    """Vistas previas pendientes, en la memoria de ESTE proceso (un uvicorn).
    Un reinicio las borra: se vuelve a subir el archivo, nada más."""

    def __init__(self, ttl: float = ONBOARDING_PREVIEW_TTL_S, clock=time.monotonic):
        self._ttl, self._clock = ttl, clock
        self._items: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def put(self, payload: Dict[str, Any]) -> str:
        token = secrets.token_urlsafe(18)
        with self._lock:
            now = self._clock()
            for k in [k for k, v in self._items.items() if v["at"] + self._ttl < now]:
                del self._items[k]
            owned = [k for k, v in self._items.items()
                     if v["payload"]["client"] == payload["client"]]
            if len(owned) >= ONBOARDING_MAX_PREVIEWS_PER_CLIENT:
                del self._items[owned[0]]
            if len(self._items) >= ONBOARDING_MAX_PREVIEWS:
                del self._items[next(iter(self._items))]
            self._items[token] = {"at": now, "payload": payload}
        return token

    def get(self, token: str, client: str) -> Dict[str, Any]:
        with self._lock:
            item = self._items.get(token or "")
            if item is None or item["payload"].get("client") != client:
                raise OnboardingError(404, "esa vista previa no existe; sube el archivo otra vez")
            if item["at"] + self._ttl < self._clock():
                del self._items[token]
                raise OnboardingError(410, "la vista previa expiró; sube el archivo otra vez")
            return item["payload"]

    def discard(self, token: str) -> None:
        with self._lock:
            self._items.pop(token, None)


PREVIEWS = PreviewStore()


def checklist(memory: Any, client: str, whatsapp_ok: bool) -> Dict[str, Any]:
    """¿Puede este agente salir a producción? Cada ítem dice qué falta y qué hacer."""
    knowledge = memory.get_client_knowledge(client)
    try:
        manual = manual_text(knowledge)
        faqs = len(faq_entries(knowledge))
        roto = ""
    except OnboardingError as e:
        manual, faqs, roto = knowledge.strip(), 0, e.motivo
    productos = len(normalize_pricing(memory.get_client_pricing(client)).get("items", []))
    huecos = len(memory.list_knowledge_gaps(client))
    items = [
        {"clave": "ficha", "ok": bool(manual) and not roto,
         "detalle": roto or (f"{len(manual)} caracteres escritos a mano" if manual
                               else "la ficha no tiene texto propio fuera de lo importado"),
         "accion": "" if manual and not roto else
                   "escribe en la ficha qué vende la empresa, horarios, despacho y formas de pago"},
        {"clave": "catalogo", "ok": productos > 0,
         "detalle": f"{productos} productos con precio",
         "accion": "" if productos else "sube el catálogo (plantilla de catálogo)"},
        {"clave": "faq", "ok": faqs > 0,
         "detalle": f"{faqs} preguntas frecuentes",
         "accion": "" if faqs else "sube las preguntas frecuentes (plantilla de FAQ)"},
        {"clave": "whatsapp_conectado", "ok": bool(whatsapp_ok),
         "detalle": "credenciales de WhatsApp cargadas" if whatsapp_ok
                    else "sin credenciales de WhatsApp para esta empresa",
         "accion": "" if whatsapp_ok else "carga el token y el phone ID de WhatsApp en Configuración"},
        {"clave": "huecos_abiertos", "ok": huecos == 0,
         "detalle": f"{huecos} preguntas que el agente no supo responder",
         "accion": "" if huecos == 0 else "responde los huecos de conocimiento pendientes"},
    ]
    for item in items:
        item["obligatorio"] = item["clave"] in ONBOARDING_CHECKLIST_REQUIRED
    listo = all(i["ok"] for i in items if i["obligatorio"])
    return {"client": client, "listo": listo, "items": items}
