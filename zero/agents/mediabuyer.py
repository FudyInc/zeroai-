"""MEDIABUYER — gestor de campañas Meta Ads con Claude.

Analiza las campañas de un cliente (CPL, gasto, leads, zona) contra el CPL objetivo
del mercado chileno (foco Santiago) y propone un plan de gestión: escalar las de
mejor CPL, pausar/realojar las de CPL alto, priorizar leads y geo Santiago.

Con `action="improve_ad"` mira UN anuncio pagado (creatividad + métricas) y sugiere
cómo mejorar su texto y su imagen, citando solo cifras que vienen en el anuncio.

Recomienda; NO gasta. Aplicar cambios es una acción aparte y confirmada, y solo
cuando Meta esté conectado de verdad. Mock determinista para construir/demostrar;
el modelo real (prompts/mediabuyer.md) razona mejor sobre el caso.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from ..backends import extract_json
from ..config import MEDIABUYER_LOW_CTR_PCT, MEDIABUYER_MIN_IMPRESSIONS
from ..contracts import AgentResponse, TaskPayload
from .base import BaseAgent


class MediaBuyer(BaseAgent):
    name = "MEDIABUYER"
    prompt_file = "mediabuyer.md"

    def _mock_result(self, task: TaskPayload) -> Tuple[Dict[str, Any], str, Optional[str]]:
        if task.data.get("action") == "improve_ad":
            return self._mock_improve_ad(task)
        camps: List[Dict[str, Any]] = list(task.data.get("campaigns") or [])
        good = int(task.data.get("good_cpl_clp") or 6000)

        recs: List[Dict[str, Any]] = []
        best = None
        best_cpl = None
        for c in camps:
            cpl = c.get("cpl_clp") or 0
            leads = c.get("leads") or 0
            status = c.get("status")
            obj = c.get("objective")
            region = c.get("region") or "Santiago (RM)"
            if status == "active" and leads and cpl <= good:
                action = "scale"
                reason = f"CPL ${cpl:,} bajo el objetivo (${good:,}). Subí presupuesto manteniendo {region}."
                if best is None or cpl < best_cpl:
                    best, best_cpl = c, cpl
            elif status == "active" and leads and cpl > good:
                action = "reallocate"
                reason = f"CPL ${cpl:,} sobre el objetivo (${good:,}). Bajá presupuesto y realojá a la de mejor CPL."
            elif status == "active" and obj != "OUTCOME_LEADS" and not leads:
                action = "reallocate"
                reason = "No trae leads. Realojá el gasto a campañas de leads en Santiago."
            elif status == "active" and obj == "OUTCOME_LEADS" and not leads:
                # leads=0 y cpl=0: activa pero sin resultados todavía (p.ej. insights
                # de Meta aún no conectados) — no es "rendimiento aceptable", es "sin dato".
                action = "keep"
                reason = "Activa pero sin leads reportados todavía. Espera unos días o revisa que los insights de Meta estén conectados."
            elif status == "paused":
                action = "keep"
                reason = "Pausada. Reactivá solo si liberás presupuesto de una de CPL alto."
            else:
                action = "keep"
                reason = "Rendimiento aceptable. Sin cambios por ahora."
            recs.append({"campaign_id": c.get("id"), "name": c.get("name"), "action": action, "reason": reason})

        if best:
            plan = (f"Foco leads + Santiago. Escalá «{best['name']}» (mejor CPL ${best_cpl:,}), "
                    f"realojá el gasto de las de CPL > ${good:,}, y pausá lo que no trae leads. "
                    f"Mantené el objetivo de CPL ≤ ${good:,} para Chile.")
        else:
            plan = (f"Ninguna campaña está bajo el CPL objetivo (${good:,}). Concentrá presupuesto en "
                    f"una sola campaña de leads en Santiago y optimizá creativos antes de escalar.")

        return {"recommendations": recs, "plan": plan}, "done", f"{len(recs)} recomendaciones (mock)"

    # --- improve_ad: mejorar UN anuncio pagado ---------------------------------
    # Entra un item de GET /api/campaigns/ads:
    #   {ad_id, ad_name, campaign_name, status,
    #    creative{title, body, image_url, call_to_action},
    #    spend, impressions, reach, clicks, ctr, leads, cpl}
    # Sale:
    #   {diagnostico, pocos_datos, sugerencias[{campo, actual, propuesta, por_que}],
    #    metricas_usadas[{metrica, valor}]}
    #
    # El prompt va acá y no en prompts/mediabuyer.md porque aquel describe la tarea de
    # campañas con su propio formato de salida; mezclar dos contratos en un prompt es
    # pedirle al modelo que adivine cuál toca.

    def run(self, task: TaskPayload) -> AgentResponse:
        if task.data.get("action") == "improve_ad" and not self.mock:
            return self._run_improve_ad(task)
        return super().run(task)

    def _run_improve_ad(self, task: TaskPayload) -> AgentResponse:
        ad = _ad(task)
        ctx = _contexto_ad(task)
        user = json.dumps({"ad": ad, **ctx}, ensure_ascii=False)
        motivo = ""
        # Dos intentos: el segundo le dice al modelo exactamente qué cifra inventó.
        # Un motor local de 14b suele corregirse con eso; si no, se informa el error
        # en vez de mostrar una cifra que el anuncio no tiene.
        for _ in range(2):
            turno = user if not motivo else f"{user}\n\nCORRIGE: {motivo}"
            try:
                raw = self.backend.complete(IMPROVE_AD_PROMPT, turno, self.model)
            except Exception as e:  # noqa: BLE001 — backend caído: se informa, no se tapa
                return AgentResponse(task.task_id, self.name, "error", {}, f"backend falló: {e}")
            data = extract_json(raw)
            if not isinstance(data, dict):
                motivo = "responde SOLO con el objeto JSON pedido."
                continue
            if isinstance(data.get("result"), dict):
                data = data["result"]
            result = _normalizar_ad(data, ad, ctx)
            if not result["diagnostico"]:
                motivo = "falta el campo diagnostico."
                continue
            ajenas = cifras_ajenas(result, ad, ctx)
            if ajenas:
                motivo = ("usaste cifras que no vienen en el anuncio: " + ", ".join(ajenas)
                          + ". Cita solo los valores tal como vienen; no calcules porcentajes ni diferencias.")
                continue
            return AgentResponse(task.task_id, self.name, "done", result,
                                 f"{len(result['sugerencias'])} sugerencias")
        return AgentResponse(task.task_id, self.name, "error", {},
                             f"el modelo no entregó sugerencias válidas: {motivo}")

    def _mock_improve_ad(self, task: TaskPayload) -> Tuple[Dict[str, Any], str, Optional[str]]:
        ad = _ad(task)
        ctx = _contexto_ad(task)
        cr = ad.get("creative") or {}
        ctr, cpl, leads = ctx["ctr_pct"], _num(ad.get("cpl")), _num(ad.get("leads"))
        good, piso, sen = ctx["good_cpl_clp"], ctx["low_ctr_pct"], ctx["senales"]

        sug: List[Dict[str, Any]] = []
        if sen["ctr_bajo"]:
            por_que = f"CTR {_fmt(ctr)}% bajo el piso de {_fmt(piso)}%: el anuncio no detiene el scroll."
            sug.append({"campo": "title", "propuesta": "Abre con el beneficio concreto para tu cliente, no con el nombre de la marca.",
                        "por_que": por_que})
            sug.append({"campo": "imagen", "propuesta": "Muestra el producto en uso real, con una sola idea visual y poco texto encima.",
                        "por_que": por_que})
        if sen["cpl_sobre_objetivo"]:
            por_que = f"CPL ${_fmt(cpl)} sobre el objetivo de ${_fmt(good)}: el clic llega pero no se convierte en lead."
            sug.append({"campo": "body", "propuesta": "Di para quién es, qué resuelve y qué pasa al dejar los datos; quita lo genérico.",
                        "por_que": por_que})
            sug.append({"campo": "call_to_action", "propuesta": "Usa un llamado que anticipe el paso siguiente, como «Solicitar cotización».",
                        "por_que": por_que})
        if sen["clics_sin_leads"]:
            sug.append({"campo": "call_to_action", "propuesta": "Pide el contacto de forma explícita: «Quiero que me llamen».",
                        "por_que": f"{_fmt(_num(ad.get('clicks')))} clics y ningún lead: el anuncio no pide el siguiente paso."})
        if not (cr.get("call_to_action") or "").strip() and not any(s["campo"] == "call_to_action" for s in sug):
            sug.append({"campo": "call_to_action", "propuesta": "Agrega un llamado a la acción de leads, como «Solicitar cotización».",
                        "por_que": "El anuncio no tiene llamado a la acción."})

        if sug:
            diag = "El anuncio tiene margen de mejora en el texto y la creatividad."
        elif cpl is not None and leads and cpl <= good:
            diag = f"Rinde bien: CPL ${_fmt(cpl)} dentro del objetivo de ${_fmt(good)}. Prueba una variante sin tocar la original."
        else:
            diag = "Sin señales claras de qué mejorar con las métricas disponibles."
        result = _normalizar_ad({"diagnostico": diag, "sugerencias": sug}, ad, ctx)
        return result, "done", f"{len(result['sugerencias'])} sugerencias (mock)"


IMPROVE_AD_PROMPT = """Eres MEDIABUYER, media buyer senior de Meta Ads para el mercado chileno (foco Santiago).
Recibes UN anuncio pagado con su creatividad y sus métricas reales. Tu trabajo: diagnosticar
por qué rinde como rinde y proponer cómo mejorar su texto y su creatividad. Recomiendas; no publicas ni gastas.

Datos que recibes (JSON):
- ad.creative: title, body, image_url, call_to_action (lo que hoy se muestra).
- ad: spend (CLP), impressions, reach, clicks, ctr (en %), leads, cpl (CLP). Un valor null es "sin dato".
- good_cpl_clp: CPL objetivo en CLP. low_ctr_pct: CTR bajo el cual el anuncio no llama la atención.
- ctr_pct: el CTR ya expresado en %. Cítalo a él.
- min_impressions y pocos_datos: si pocos_datos es true, el diagnóstico DEBE decir "pocos datos para concluir".
- senales: comparaciones YA calculadas (ctr_bajo, cpl_sobre_objetivo, clics_sin_leads). Son la verdad:
  no las contradigas ni las recalcules. Si ctr_bajo es true, el CTR NO es aceptable.

Cómo razonar:
- CTR bajo low_ctr_pct → el problema está en title e imagen (no detiene el scroll).
- CTR aceptable pero cpl sobre good_cpl_clp → el problema está en body y call_to_action (el clic no convierte).
- Clics sin leads → el anuncio no pide el siguiente paso.
- Cada por_que DEBE citar el valor de la métrica que lo justifica, copiado de los datos
  (ej.: "CTR 0.5% bajo el piso de 1.0%", "CPL 12500 sobre el objetivo de 6000").

Regla dura sobre cifras: usa SOLO números que vengan en los datos, tal como vienen. No calcules
porcentajes, diferencias ni proyecciones. No inventes ofertas, descuentos, urgencias ("oferta limitada"),
plazos, garantías ni precios: la propuesta solo puede usar lo que el anuncio ya dice o el negocio ya ofrece.
En "propuesta" escribe el texto nuevo listo para usar (para imagen: describe la imagen).

Responde SOLO con este JSON, sin texto fuera:
{"diagnostico": "1-2 frases",
 "sugerencias": [{"campo": "title|body|call_to_action|imagen", "propuesta": "...", "por_que": "..."}]}
"""

_CAMPOS = {"title": "title", "titulo": "title", "título": "title", "headline": "title",
           "body": "body", "texto": "body", "cuerpo": "body",
           "call_to_action": "call_to_action", "cta": "call_to_action",
           "imagen": "imagen", "image": "imagen", "image_url": "imagen", "creatividad": "imagen"}
_METRICAS = ("spend", "impressions", "reach", "clicks", "ctr", "leads", "cpl")
_POCOS_DATOS = "pocos datos para concluir"


def _ad(task: TaskPayload) -> Dict[str, Any]:
    ad = task.data.get("ad")
    return ad if isinstance(ad, dict) else {}


def _contexto_ad(task: TaskPayload) -> Dict[str, Any]:
    ad = _ad(task)
    good = _num(task.data.get("good_cpl_clp"))
    if good is None:
        from ..metaads import CHILE
        good = CHILE["good_cpl_clp"]
    impr = _num(ad.get("impressions"))
    ctr, cpl = _ctr_pct(ad), _num(ad.get("cpl"))
    leads, clicks = _num(ad.get("leads")), _num(ad.get("clicks"))
    # Las señales se calculan acá y se le pasan al modelo: un 14b local que compara
    # 0.5 contra 1.0 a veces concluye "CTR aceptable". La aritmética no es su trabajo.
    senales = {
        "ctr_bajo": ctr is not None and ctr < MEDIABUYER_LOW_CTR_PCT,
        "cpl_sobre_objetivo": cpl is not None and bool(leads) and cpl > good,
        "clics_sin_leads": bool(clicks) and not leads,
    }
    return {"good_cpl_clp": good, "low_ctr_pct": MEDIABUYER_LOW_CTR_PCT,
            "min_impressions": MEDIABUYER_MIN_IMPRESSIONS, "ctr_pct": ctr,
            "pocos_datos": impr is None or impr < MEDIABUYER_MIN_IMPRESSIONS,
            "senales": senales}


def _ctr_pct(ad: Dict[str, Any]) -> Optional[float]:
    """CTR en %. Meta lo entrega en %; si clics/impresiones dicen que vino como
    fracción (0.005 en vez de 0.5), se pasa a %. Sin cómo comprobarlo, se asume %."""
    ctr = _num(ad.get("ctr"))
    clicks, impr = _num(ad.get("clicks")), _num(ad.get("impressions"))
    if ctr is None or not clicks or not impr:
        return ctr
    real = clicks / impr * 100
    return ctr * 100 if abs(ctr * 100 - real) < abs(ctr - real) else ctr


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt(v: float) -> str:
    """Cifra a la chilena: punto de miles y coma decimal (6.000 · 0,5 · 8.333,33)."""
    if float(v).is_integer():
        return f"{int(v):,}".replace(",", ".")
    ent, dec = f"{v:,.2f}".split(".")
    return ent.replace(",", ".") + ("," + dec.rstrip("0") if dec.rstrip("0") else "")


def _actual(ad: Dict[str, Any], campo: str) -> str:
    cr = ad.get("creative") or {}
    return str(cr.get("image_url" if campo == "imagen" else campo) or "")


def _normalizar_ad(data: Dict[str, Any], ad: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Lleva cualquier respuesta (modelo o mock) al contrato. `actual` sale siempre del
    anuncio, nunca del modelo: así no puede citar mal lo que hoy se muestra."""
    diag = str(data.get("diagnostico") or "").strip()
    if diag and ctx["pocos_datos"] and _POCOS_DATOS not in diag.lower():
        impr = _num(ad.get("impressions"))
        cuantas = f"{_fmt(impr)} impresiones" if impr is not None else "sin impresiones reportadas"
        diag = (f"Pocos datos para concluir ({cuantas}; se necesitan al menos "
                f"{_fmt(ctx['min_impressions'])}). {diag}")
    sugerencias: List[Dict[str, Any]] = []
    for s in data.get("sugerencias") or []:
        if not isinstance(s, dict):
            continue
        campo = _CAMPOS.get(str(s.get("campo") or "").strip().lower())
        propuesta = str(s.get("propuesta") or "").strip()
        por_que = str(s.get("por_que") or "").strip()
        if campo and propuesta and por_que:
            if not _cita_metrica(por_que, ad):
                cita = _cita(campo, ad, ctx)
                por_que = f"{por_que.rstrip('. ')} ({cita})." if cita else por_que
            sugerencias.append({"campo": campo, "actual": _actual(ad, campo),
                                "propuesta": propuesta, "por_que": por_que})
    result = {"diagnostico": diag, "pocos_datos": ctx["pocos_datos"],
              "sugerencias": sugerencias, "metricas_usadas": []}
    citadas = [n for n in _numeros(_textos(result))]
    result["metricas_usadas"] = [
        {"metrica": m, "valor": ad[m]} for m in _METRICAS
        if _variantes(m, ad) and any(_coincide(n, _variantes(m, ad)) for n in citadas)
    ]
    return result


def _cita_metrica(texto: str, ad: Dict[str, Any]) -> bool:
    return any(_coincide(n, _variantes(m, ad)) for n in _numeros([texto]) for m in _METRICAS)


def _cita(campo: str, ad: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    """La métrica que justifica tocar `campo`, con valores del anuncio. El modelo a
    veces argumenta bien y no cita nada; el pedido es que cada por_que cite."""
    ctr, cpl = ctx["ctr_pct"], _num(ad.get("cpl"))
    clicks, leads = _num(ad.get("clicks")), _num(ad.get("leads"))
    ctr_txt = f"CTR {_fmt(ctr)}% vs piso de {_fmt(ctx['low_ctr_pct'])}%" if ctr is not None else ""
    if campo in ("body", "call_to_action"):
        if cpl is not None and leads:
            return f"CPL ${_fmt(cpl)} vs objetivo de ${_fmt(ctx['good_cpl_clp'])}"
        if clicks is not None and leads is not None:
            return f"{_fmt(clicks)} clics, {_fmt(leads)} leads"
    return ctr_txt


def _textos(result: Dict[str, Any]) -> List[str]:
    # `actual` no se revisa: es la creatividad del propio anuncio.
    out = [result.get("diagnostico") or ""]
    for s in result.get("sugerencias") or []:
        out += [s.get("propuesta") or "", s.get("por_que") or ""]
    return out


_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")


def _lecturas(tok: str) -> List[float]:
    """Lecturas posibles de un número escrito. Solo «1.000»/«1,000» (un separador y
    tres dígitos detrás) es ambiguo; el resto tiene una sola lectura:
    «12.500,5» → 12500.5 · «1.234.567» → 1234567 · «0,8» → 0.8 · «8333.33» → 8333.33."""
    if "." in tok and "," in tok:
        miles, dec = (".", ",") if tok.rfind(",") > tok.rfind(".") else (",", ".")
        return [float(tok.replace(miles, "").replace(dec, "."))]
    sep = "." if "." in tok else ("," if "," in tok else "")
    if not sep:
        return [float(tok)]
    partes = tok.split(sep)
    if len(partes) > 2:
        return [float("".join(partes))]
    if len(partes[1]) == 3:
        return [float("".join(partes)), float(".".join(partes))]
    return [float(".".join(partes))]


def _numeros(textos: List[str]) -> List[List[float]]:
    return [_lecturas(tok) for t in textos for tok in _NUM_RE.findall(t)]


def _variantes(metrica: str, ad: Dict[str, Any]) -> List[float]:
    v = _num(ad.get(metrica))
    if v is None:
        return []
    if metrica == "ctr":
        # Solo el valor tal cual y su lectura en %; nunca «v×100 por si acaso»: con un
        # CTR de 0.5 eso dejaba pasar «50% de descuento».
        pct = _ctr_pct(ad)
        return sorted({v, pct}) if pct is not None else [v]
    return [v]


def _coincide(lecturas: List[float], permitidos: List[float]) -> bool:
    """Igual, o el permitido redondeado a 2 o 1 decimal (o a entero si es ≥ 10).
    «0,55» no es un CTR de 0.5; «8.333» sí es un CPL de 8333.33."""
    for n in lecturas:
        for a in permitidos:
            redondeos = {round(a, 2), round(a, 1)} | ({float(round(a))} if abs(a) >= 10 else set())
            if abs(n - a) <= abs(a) * 1e-6 + 1e-9 or any(abs(n - r) < 1e-9 for r in redondeos):
                return True
    return False


def cifras_ajenas(result: Dict[str, Any], ad: Dict[str, Any], ctx: Dict[str, Any]) -> List[str]:
    """Números que aparecen en el texto del resultado y no salen del anuncio ni de la
    política (objetivo de CPL, umbrales). Vacío = no inventó cifras."""
    permitidos: List[float] = []
    for m in _METRICAS:
        permitidos += _variantes(m, ad)
    permitidos += [ctx["good_cpl_clp"], ctx["low_ctr_pct"], ctx["min_impressions"]]
    cr = ad.get("creative") or {}
    propios = [str(cr.get(k) or "") for k in ("title", "body", "call_to_action")]
    propios += [str(ad.get(k) or "") for k in ("ad_name", "campaign_name")]
    for lecturas in _numeros(propios):
        permitidos += lecturas
    ajenas: List[str] = []
    for t in _textos(result):
        for tok in _NUM_RE.findall(t):
            if not _coincide(_lecturas(tok), permitidos) and tok not in ajenas:
                ajenas.append(tok)
    return ajenas


def improve_ad(zero: Any, ad: Dict[str, Any], good_cpl_clp: Optional[float] = None,
               client_id: str = "") -> Dict[str, Any]:
    """Punto de entrada para CORE: `_agent_op(lambda z: improve_ad(z, item, CHILE["good_cpl_clp"], client))`.

    Si el motor falla o no entrega sugerencias válidas, levanta RuntimeError con el
    motivo — nunca devuelve una plantilla en su lugar (CLAUDE.md, principio 1)."""
    if good_cpl_clp is None:
        from ..metaads import CHILE
        good_cpl_clp = CHILE["good_cpl_clp"]
    resp = zero.dispatch("MEDIABUYER", TaskPayload(
        agent="MEDIABUYER", client_id=client_id or "", client_tier="",
        instructions="Sugiere cómo mejorar el texto y la creatividad de este anuncio pagado.",
        data={"action": "improve_ad", "ad": ad or {}, "good_cpl_clp": good_cpl_clp},
    ))
    if resp.status == "error":
        raise RuntimeError(resp.notes or "MEDIABUYER no pudo analizar el anuncio")
    return resp.result
