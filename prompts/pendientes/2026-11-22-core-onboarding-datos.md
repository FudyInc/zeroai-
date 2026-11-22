[TARGET: ⚙️ CORE] — si tu sección / $CLAUDE_ROLE no es CORE, detente y dilo.

OBJETIVO
Que una empresa cliente nueva pueda dejar lista la base de conocimiento de su agente de
WhatsApp subiendo UN archivo (CSV o XLSX) de catálogo/precios y uno de preguntas
frecuentes, con vista previa antes de aplicar, versionado y una lista de chequeo que diga
si el agente ya puede salir a producción.

CONTEXTO (lo que no sale del repo)
- Diego, 2026-11-22: "la empresa que contrate nuestros servicios solo tenga que meter su
  base de datos para que el agente funcione en su canal de WhatsApp".
- YA EXISTE y se reutiliza — no se construye un almacén paralelo:
  · Ficha de empresa (texto libre, versionada, con rollback): `/api/knowledge`,
    `/api/knowledge/versions`, `/api/knowledge/rollback` (api.py ~2934) →
    `memory.set_client_knowledge(client, texto, motivo=...)`.
  · Precios por cliente: `/api/pricing` (api.py ~3041) → `memory.get/set_client_pricing`,
    normalizados con `normalize_pricing` / `client_pricing`.
  · Huecos de conocimiento: `memory.list_knowledge_gaps`.
  · Credenciales de canal por cliente: `zero/client_integrations.py::configured(client, "whatsapp")`.
  · Recorte de la ficha por pregunta: `zero/whatsapp_context.py::select_knowledge`
    (parte la ficha por párrafos en blanco).
- "Base de datos" en v1 = ARCHIVO (CSV/XLSX), no conexión directa a Postgres/MySQL/Shopify.
  La conexión directa queda fuera de alcance (es un frente nuevo con credenciales y costo).
- PoolEdge (id `losetaschile`) está en producción con un agente afinado a mano
  (`zero/losetas_*.py`, pesos en código). Una importación NO puede pisar sus datos.

ALCANCE
Puedes tocar: `api.py` (endpoints nuevos bajo `/api/onboarding/`), un módulo nuevo
`zero/onboarding.py`, `zero/config.py` (solo constantes nuevas de onboarding),
`tests/test_onboarding.py` (nuevo).
NO tocar: `frontend/`, `zero/agents/`, `zero/losetas_*.py`, `zero/whatsapp_*.py`,
`prompts/*.md`, `state.json`, `crm.json`. Hay terminales de WhatsApp con trabajo en vuelo
en esos archivos (ramas `feat/responder-atrasados`, `feat/grupo-envia-presupuesto`,
`feat/agente-sin-eco` con WIP sin commitear).

PASO 0 — rama
Este worktree (`/home/diego/zero-core`, rama `core-anuncios`) va 128 commits atrás de
`origin/main` y tiene 1 commit propio que main no tiene (`8bb8512 fix(persistence): Never
let state.json or crm.json vanish while saving` — `git cherry origin/main core-anuncios`
lo marca con `+`). NO hagas rebase. Deja `core-anuncios` intacta, `git fetch origin` y
crea `feat/onboarding-datos` desde `origin/main`. Al final reporta si `8bb8512` sigue
haciendo falta en main (compáralo con `zero/persistence.py` actual), sin fusionarlo.

CONTRATO (DASHBOARD construye contra esto — si lo cambias, repórtalo explícitamente)
1. `GET /api/onboarding/template?kind=catalogo|faq` → CSV (text/csv) con encabezados.
   - catalogo: `sku,nombre,categoria,precio,unidad,descripcion,stock` (precio y nombre obligatorios)
   - faq: `pregunta,respuesta` (ambas obligatorias)
2. `POST /api/onboarding/preview?client=X` body JSON
   `{"kind": "catalogo"|"faq", "filename": str, "content_base64": str}`
   → `{"rows": [...normalizadas], "errors": [{"fila": n, "columna": str, "motivo": str}],
       "summary": {"validas": n, "con_error": n, "nuevas": n, "cambian": n, "sin_cambio": n},
       "token": str}`. NO escribe nada.
   (JSON + base64 a propósito: `UploadFile` exige `python-multipart`, y el núcleo es solo stdlib.)
3. `POST /api/onboarding/apply?client=X` body `{"token": str, "motivo": str}` → aplica la
   vista previa de ese token (expira; config). Devuelve la versión nueva de la ficha.
4. `GET /api/onboarding/status?client=X` → `{"listo": bool, "items": [{"clave", "ok",
   "detalle", "accion"}]}` con al menos: ficha, catalogo, faq, whatsapp_conectado,
   huecos_abiertos. `listo` = todos los obligatorios ok.
Mismas reglas de rol/alcance que `/api/knowledge` (`_require_client`, `_ROLE_ALLOWED`).

DECISIONES YA TOMADAS
- Parseo con stdlib: CSV con `csv.Sniffer` (`,` o `;`, UTF-8 con o sin BOM, y latin-1 de
  respaldo); XLSX con `zipfile` + `xml.etree` (primera hoja, shared strings, sin fórmulas).
  Cero dependencias nuevas.
- Precios en CLP enteros; aceptar `$12.990`, `12990`, `12.990,00`. Fila con precio
  ilegible = error de esa fila, nunca 0.
- Catálogo → `set_client_pricing` (respetando el formato que lee `normalize_pricing`; léelo,
  no lo supongas) Y una sección generada en la ficha, delimitada por marcadores
  (`<!-- catalogo:inicio -->` / `<!-- catalogo:fin -->`), en párrafos que
  `select_knowledge` pueda recortar. FAQ → otra sección delimitada igual. Cada import
  regenera SOLO su sección; el texto manual de la ficha no se toca jamás.
- Todo apply pasa por `set_client_knowledge(..., motivo="importación <archivo>")` para que
  quede versionado y el rollback existente sirva.
- Antes de decidir lo anterior, VERIFICA con código cómo el camino genérico de WhatsApp
  (no PoolEdge) lee precios: si no lee `client_pricing`, la sección en la ficha es la que
  manda. Reporta lo que encuentres con archivo:línea.

CONSTRAINTS (principios de CLAUDE.md, vigentes hoy)
- Operación real: nada de mock fuera de tests. Sin motor/datos, el endpoint responde con
  el motivo, no con una plantilla.
- Política en config.py: `ONBOARDING_MAX_BYTES` (p.ej. 2 MB), `ONBOARDING_MAX_ROWS`
  (p.ej. 2000), `ONBOARDING_PREVIEW_TTL_S`, columnas obligatorias por kind, los ítems
  obligatorios del checklist, y `ONBOARDING_LOCKED_CLIENTS = frozenset({"losetaschile"})`
  → apply responde 409 con motivo para esos clientes (preview sí funciona).
- Solo stdlib. Política de cero gasto.
- Supabase: con Supabase activo las escrituras van a la nube. Prueba con tests y con un
  cliente de prueba, NUNCA contra datos de un cliente real.
- `git status` antes de editar.

ACEPTACIÓN
- `python3 -m unittest discover -s tests -t .` en verde.
- `tests/test_onboarding.py` cubre: CSV con `;` y BOM, XLSX mínimo generado en el test,
  precio ilegible → error de fila, preview no escribe, apply regenera solo su sección y deja
  intacto el texto manual, segundo apply crea versión nueva y rollback la revierte,
  `losetaschile` → 409, archivo sobre el límite → 413, status con y sin WhatsApp conectado.
- Corrida real: `curl` de template → preview → apply → status contra la API local con un
  cliente de prueba; pega la salida en el reporte.

REPORTE
Resumen corto de lo cambiado, el contrato final (si difiere de arriba, el diff), el hallazgo
sobre cómo el camino genérico lee precios, el estado de `8bb8512`, y cualquier cosa fuera
de CORE que haya que arreglar (repórtala, no la arregles).
