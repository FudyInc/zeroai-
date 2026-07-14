# Roadmap — archivo histórico

Detalle completo de rondas de trabajo ya cerradas, movido aquí desde
`docs/roadmap.md` (2026-07-13) para que el documento activo sea rápido de leer.
`roadmap.md` mantiene un resumen corto de cada punto con link hacia acá — este
archivo es la referencia, no hace falta leerlo entero salvo que necesites el
detalle de un bug/fix específico (causa raíz, archivo, tests). Nada de esto se
borra nunca (ver [[zero-roadmap]]): es historial versionado, no memoria viva.

---

## Plan de fiabilidad (detalle completo)

Criterio original: no lanzar hasta que esto esté resuelto **de verdad**, no "se
siente listo". Orden acordado con Diego. (El punto 2, fragilidad del hosting,
sigue abierto — ⏸️ pausado a propósito — y por eso se quedó en `roadmap.md`, no
está acá.)

1. **Plantillas de WhatsApp Business (Meta)** — ✅ CÓDIGO LISTO (2026-07-04), falta
   el paso manual de Diego. Confirmado en código: `WhatsAppSender.send()`
   (`zero/channels.py`) siempre mandaba `type: "text"`. Meta EXIGE una plantilla
   pre-aprobada para el primer contacto a un lead que nunca escribió, o cualquier
   mensaje fuera de la ventana de 24h desde su último mensaje — un `type: "text"` en
   frío es rechazado por la Graph API real. Afecta: `_send_first_touch` y
   `run_followups` (orchestrator.py). NO afecta las respuestas dentro de
   `handle_inbound` (son réplica a algo que el lead ya escribió, dentro de la ventana
   de 24h — texto libre está bien ahí).
   **Hecho:** `WHATSAPP_TEMPLATE` en `zero/config.py`; `WhatsAppSender` soporta
   `type: "template"` (`_template_body`) y sigue soportando texto libre (`_text_body`)
   para las respuestas; orchestrator marca `whatsapp_send_type: "template"` solo en
   los dos puntos de contacto en frío; sin plantilla configurada, degrada a error
   visible en el CRM (nunca manda texto libre que Meta rechazaría en silencio). 5
   tests nuevos, 297/297 en verde. Instrucciones para Diego en `docs/GO-LIVE.md` §(c).
   **Falta (fuera de código, manual):** Diego crea la plantilla en Meta Business
   Manager, espera aprobación, y la anota en `WHATSAPP_TEMPLATE`.
3. **Test end-to-end HTTP** — ✅ HECHO (2026-07-04). `tests/test_api_http.py`: levanta
   `api.py` real como subproceso (`uvicorn`) y le pega con HTTP real (stdlib puro —
   `subprocess`+`urllib`, SIN `httpx`/`TestClient`, cero dependencias nuevas más allá
   de lo que `api.py` ya necesita). Corre solo, y se salta a sí mismo (skip limpio)
   si `uvicorn` no está instalado — separado de `test_core.py`, que sigue siendo
   100% stdlib.
   **Encontró un bug real al primer uso:** `GET /api/clients` tiraba `500` crudo
   cuando `SUPABASE_URL`/`SUPABASE_KEY` estaban configuradas pero Supabase no
   respondía (`SupabaseError` sin capturar). Causa: `make_crm()`/`SupabaseCRM` cargan
   perezoso a propósito (no hacen `SELECT *` — ver escalabilidad más abajo), así que
   el fallo real aparece recién al primer query, no al construir el objeto —
   `make_memory()` sí tenía ese fallback (con try/except en la construcción),
   `make_crm()` no tenía ninguno.
   **Arreglado:** manejador de excepción global en `api.py`
   (`@app.exception_handler(SupabaseError)`) que convierte CUALQUIER `SupabaseError`
   sin capturar, en cualquier endpoint, a un `503` con mensaje claro — en vez de un
   `500` genérico. Cubre tanto `crm_supabase.py` como `memory_supabase.py` (comparten
   la misma excepción). Test de regresión agregado. 302/302 tests en verde.
4. Checklist de fiabilidad — ✅ CÓDIGO LISTO (2026-07-04). Los 4 ítems de código
   (firma del webhook, reintentos de envío, backup de crm.json/state.json,
   casos difíciles de CONCIERGE, expiración de sesión) están hechos y probados.
   Quedan 2 puntos que son acción manual de Diego (anotados, no bloquean nada
   de código): password real en vez de la de prueba, vendedores con números
   reales de WhatsApp Business (en curso — bloqueado hoy por la verificación
   de cuenta personal de Meta, ver docs/GO-LIVE.md §(c)). Prueba en móvil
   **descartada a propósito** (2026-07-04): el dashboard es propietario, solo
   la agencia lo opera, y siempre desde computador — no aporta nada probarlo
   en celular.
   - **Verificación de firma del webhook de Meta** — ✅ HECHO. `POST
     /api/webhooks/whatsapp` no verificaba nada — cualquiera con la URL podía
     mandar mensajes falsos haciéndose pasar por un lead (y hasta gatillar una
     respuesta real con `OUTBOX_LIVE=1`). Agregado `verify_meta_signature` en
     `zero/whatsapp_inbound.py` (HMAC-SHA256 contra `WHATSAPP_APP_SECRET`,
     comparación con `hmac.compare_digest`); sin el secreto configurado, o con una
     firma que no cuadra, el webhook rechaza con `403` — no hay forma de recibir
     mensajes reales sin el secreto. `WHATSAPP_APP_SECRET` sumado a
     `POST /api/config` y a `docs/GO-LIVE.md`. 4 tests nuevos (función aislada +
     HTTP real). 306/306 tests en verde.
   - **Reintentos de envío fallido** — ✅ HECHO (2026-07-04). `Outbox.send()` no
     reintentaba nada: un corte de red momentáneo (timeout SMTP, blip de la Graph
     API) degradaba el envío a `"error"` para siempre en el primer intento fallido,
     sin darle ninguna chance a un problema transitorio. Agregado
     `OUTBOX_RETRY_ATTEMPTS`/`OUTBOX_RETRY_DELAY_SECONDS` en `zero/config.py`
     (3 intentos, 1s de espera entre cada uno, configurable por instancia);
     `Outbox.send()` reintenta con esos parámetros y solo degrada a `"error"`
     cuando se agotan todos los intentos. Nunca cambia el contrato (`Outbox`
     sigue sin lanzar excepciones hacia afuera). 2 tests nuevos (reintenta y
     luego funciona / se agotan los reintentos y degrada a error), más un ajuste
     a un test viejo que sin querer empezó a dormir de verdad con la nueva
     lógica (`retry_delay=0` en los tests, para no pagar el segundo real en cada
     corrida de la suite). 308/308 tests en verde, ~1s (tiempo normal).
   - **Backup de `crm.json`/`state.json`** — ✅ HECHO (2026-07-04). `CRM.save()` y
     `SessionMemory.save()` escribían directo sobre el archivo — una escritura
     cortada a mitad de camino (crash, corte de luz, disco lleno) podía dejarlo
     corrupto, y sin ningún respaldo eso significaba perder todos los leads o
     todo el estado de sesión de un saque (`_load()` ya avisaba con
     `RuntimeError` en vez de arrancar vacío, pero no había forma de recuperarse).
     Nuevo módulo compartido `zero/persistence.py` (`save_json`/`load_json`):
     escritura atómica (temporal + `os.replace`, nunca deja un archivo a medio
     escribir) que además rota la versión anterior a `<path>.bak` antes de
     reemplazar; al leer, si el archivo principal está corrupto intenta el
     `.bak` automáticamente (con aviso claro por stderr) antes de recién ahí
     rendirse. `crm.py`/`memory.py` migrados a este módulo, sin cambiar su
     comportamiento externo. `.gitignore` cubre `*.json.bak`/`*.json.tmp`. 6
     tests nuevos (rotación, recuperación desde backup, ambos corruptos → error
     claro, extremo a extremo con `CRM` real).
     **Simulacro real en Ubuntu de producción (2026-07-06)**: con copia de
     seguridad extra hecha antes (`/tmp/backup-drill/`) y el backend detenido,
     se corrompió a propósito el `state.json` real y se confirmó que
     `make_memory()` se recupera solo desde `state.json.bak` (con el aviso por
     stderr) y que el archivo se autorepara en el siguiente `save()`. Con
     `crm.json` (que hoy **no tiene `.bak`** — no ha tenido una segunda
     escritura desde que se desplegó este mecanismo) se confirmó el otro caso:
     sin backup disponible, falla con un `RuntimeError` limpio, nunca pierde
     datos en silencio. Ambos archivos reales restaurados exactos después del
     simulacro (diff limpio contra la copia previa).
     **Hallazgo operativo**: `zero-tunnel.service` tiene `Requires=
     zero-backend.service` — detener el backend apaga el túnel en cascada
     automáticamente, y **no vuelve solo** al reiniciar el backend; hay que
     iniciar ambos servicios a mano. Bueno saberlo para cualquier
     mantención futura que pare el backend un momento.
   - **Prueba de CONCIERGE con casos difíciles** — ✅ HECHO (2026-07-04). Un
     lead real puede escribir cualquier cosa — vacío, groserías, spam, inglés,
     un mensaje gigante — y el agente nunca puede romperse por eso. Probado a
     mano primero (mensaje vacío/blanco, solo emojis, 20.000 caracteres, `None`,
     insultos con "estafa") y ninguno crashea; los 7 tests nuevos
     (`ConciergeEdgeCasesTest`) lo dejan como regresión: mensaje vacío/blanco,
     `data` sin la clave `message`, groserías (nunca las repite en la
     respuesta), spam/sin sentido, "stop" en inglés (opt-out sin traducir
     nada — misma keyword), mensaje de ~25.000 caracteres (con límite de tiempo
     para descartar un ReDoS), y lead sin nombre (el saludo no debe romperse).
   - **Expiración de sesión probada** — ✅ HECHO (2026-07-04). `zero/auth.py` ya
     tenía tests unitarios de `valid_token()` (expira, password rotada, token
     alterado), pero eso nunca probó que el middleware real de `api.py`
     (`auth_guard`) de verdad lo aplique en cada request — la lógica podía
     estar perfecta y el middleware roto, y los tests seguirían en verde.
     Agregada `ApiAuthHttpTest` en `tests/test_api_http.py`: subproceso propio
     con `AUTH_PASSWORD` configurado (separado de `ApiHttpTest`, que corre a
     propósito sin password para probar los demás endpoints libremente),
     probando sobre HTTP real: sin token → 401, token basura → 401, password
     incorrecta en `/api/login` → 401, login con token válido → 200, **token
     vencido firmado con la password real del servidor → 401** (el caso central:
     firma válida pero expirado, para separar "token falso" de "token viejo"),
     y que `/api/health`/`/api/auth/status` nunca piden token. Se extrajo
     `_wait_until_up` como función compartida del archivo (la usaban ambas
     clases). 6 tests nuevos. 327/327 tests en verde (13 de ellos en
     `test_api_http.py`, subiendo el tiempo total a ~1.8s por los dos
     subprocesos de uvicorn — el resto de la suite sigue en ~1s).

**Auditoría de ANALYST (2026-07-06)** — cierra la ronda de auditar en vivo, con
el modelo real, cada agente que redacta/opina algo de cara al negocio
(OUTREACH, TRACKER, CONCIERGE, PITCHWRITER ya arriba). A diferencia de esos
cuatro, **acá no se encontró ningún bug que arreglar**: se respetó siempre la
regla de "nunca hagas la aritmética" (nunca devolvió conteos proyectados,
solo tasas), y con muestra chica (2 contactados, vía `/api/forecast?client=
acme` real) mantuvo las tasas base con una justificación correcta y corta.
**Hallazgo de calibración (no un bug, no se arregló)**: con el modelo local
(qwen2.5:7b), ANALYST es **demasiado conservador** — probado con 80
contactados (muy por sobre el umbral de "muestra chica" que el propio prompt
define en <20), igual dijo "muestra chica" y no ajustó nada. No es peligroso
(el peor caso es un forecast un poco conservador de más, nunca inflado), pero
en la práctica significa que hoy el "juicio" de ANALYST casi nunca ajusta las
tasas con este modelo — puede mejorar con un modelo más grande (Anthropic)
más adelante; no vale la pena forzarlo con más prompting (arriesga que
empiece a inventar señales, un problema peor que ser conservador de más).

**Auditoría de MOTOR-llamadas (2026-07-13)** — auditoría de código (no en vivo,
sin necesitar el PC de Ubuntu prendido) de `zero/calls.py` (Vapi, llamadas
salientes) y `zero/voice.py` (ElevenLabs, texto→voz).
- `zero/voice.py`: limpio, bien testeado, **sin bugs**. Confirmado que sigue
  sin estar enchufado a `api.py` — es una herramienta CLI standalone, tal
  como ya lo declara `docs/voice.md` ("solo la voz, no el agente de llamadas
  completo").
- `api.py` (`/api/assistants`, `/api/vapi/numbers`, `/api/call`): envuelven
  `zero.calls` de forma limpia (`RuntimeError` → `HTTPException(400)`), sin
  rutas de crash.
- **Bug real encontrado y arreglado** en `zero/calls.py`: `list_assistants()`
  y `list_phone_numbers()` asumían que la API de Vapi siempre devuelve una
  lista JSON bare; si alguna vez la envolviera en un objeto (cambio de API,
  un 200 con otra forma), el list comprehension reventaba con
  `AttributeError` (iterando keys de un dict como si fueran items, llamando
  `.get()` sobre un string). Arreglado con guardas `isinstance(data, list)`
  (si no, devuelve `[]`) e `isinstance(x, dict)` filtrando items no-dict
  dentro de la lista.
- **Endurecido** `place_call()`: ahora valida que `number` no venga vacío
  antes de armar el body (`Falta: número a llamar`), igual que ya validaba
  key/agente/número de origen. Antes de esto, un número vacío llegaba
  igual a Vapi y el error solo aparecía como un 4xx confuso desde su API.
  Severidad baja en la práctica — el frontend (`Llamadas.jsx`) ya exige
  exactamente 9 dígitos antes de llamar al endpoint — pero la función debe
  ser segura igual si se invoca desde otro lado (script, otro cliente de la
  API).
- 8 tests nuevos en `tests/test_calls.py`: curl no disponible (en `_curl` y
  en `place_call`), número vacío, y 3 tests de la respuesta envuelta/con
  items no-dict de Vapi. 372/372 tests en verde.

**Auditoría extendida — defensivo/webhooks/discovery (2026-07-13)** — continuación
de la ronda anterior, tres frentes que no necesitan el PC de Ubuntu prendido.

1. **Mismo patrón defensivo (isinstance ante respuesta envuelta) extendido a
   `zero/metaads.py`** — la ruta REAL (`MetaAds`, `_graph`, `list_ad_accounts`,
   Meta Graph API) tenía **cero tests** hasta ahora (solo `MockMetaAds` estaba
   cubierto) y los mismos riesgos que `calls.py`: `data.get("data", [])`
   reventaría si Graph alguna vez no devuelve un dict, y un `json.loads` que
   fallara por una respuesta no-JSON se propagaba como excepción cruda en vez
   de un `RuntimeError` claro. Arreglado con las mismas guardas
   `isinstance` + degradar a `[]`/mensaje claro; `tests/test_metaads.py`
   nuevo, 12 tests (antes 0) mockeando `urllib.request.urlopen`.
   `zero/backends.py` y `zero/discovery.py` se revisaron también — ya estaban
   bien defendidos (backends.py ya capturaba `KeyError/IndexError/TypeError`
   de una respuesta rara; discovery.py nunca parsea JSON de una API, solo
   HTML con regex + `try/except Exception: return None` en cada fetch).
2. **Bug real encontrado y arreglado en `zero/whatsapp_inbound.py`**:
   `parse_inbound()` — el parser del webhook público de Meta — prometía en su
   propio docstring "malformed payloads yield [], never raise", pero si
   `entry`/`changes`/`messages` venían con otra forma (string en vez de
   lista, item no-dict) reventaba con `AttributeError` de verdad (confirmado
   reproduciendo el crash antes de arreglarlo). Arreglado con guardas
   `isinstance` en cada nivel del payload, ahora sí cumple lo que dice su
   propio contrato. 9 tests nuevos en `tests/test_core.py`. El lado de envío
   (`WhatsAppSender`/`Outbox`) ya estaba a salvo: `Outbox.send()` envuelve
   cualquier excepción del sender en un `except Exception` genérico con
   reintentos, así que un envío roto ya degradaba a `error` sin crashear —
   no hizo falta tocarlo.
3. **CONCIERGE en vivo por WhatsApp, con Ubuntu prendido (2026-07-13, misma
   tarde)** — 14 casos difíciles (mensaje vacío, solo emojis, "STOP" en
   inglés, opt-out en español, grosería, mensaje gigante, multi-pregunta,
   fuera de tema, intento de prompt injection, solo un link, mayúsculas
   agresivas, inglés, "nombre" = número de teléfono) contra el modelo real
   (qwen2.5:7b) vía `Zero.converse_result`, aislado en memoria (sin tocar
   Supabase/CRM real). Ningún crash. La lógica de ventana 24h/plantilla en
   `orchestrator.py`/`channels.py` se confirmó correcta (la respuesta a un
   lead que acaba de escribir nunca lleva `whatsapp_send_type=template`, solo
   los follow-ups en frío lo llevan). **Dos bugs reales encontrados y
   arreglados:**
   - **`intent` siempre `None` con el motor real** — causa raíz en
     `zero/contracts.py`: `AgentResponse.from_dict()` "levanta" al `result`
     solo las claves listadas en `_RESULT_KEYS` cuando el modelo responde sin
     envoltorio `{"result": {...}}` — y ese es exactamente el esquema plano
     que pide `prompts/concierge.md` (`{"reply", "intent"}`). Como `"intent"`
     no estaba en la lista, se descartaba en silencio en CADA respuesta real
     (confirmado comparando la salida cruda del modelo, que sí traía
     `"intent": "pricing"`, contra el resultado ya parseado, que lo perdía).
     Esto rompía sin avisar el flujo de "oferta pendiente" de
     `handle_inbound` (`set_pending_offer` si `intent` es `info`/`objection`)
     con el motor real — solo funcionaba en mock. Nadie lo vio antes porque
     el mock nunca pasa por `from_dict`: exactamente el escenario que advierte
     el CLAUDE.md de este repo ("el mock debe ser fiel al contrato... o da
     falsa confianza"). Un test existente en `tests/test_contracts.py`
     incluso **fijaba el bug como comportamiento esperado** — corregido junto
     con el fix. Arreglo: se agregó `"intent"` a `_RESULT_KEYS`.
   - **Mensaje entrante desmedido → reply vacío** — un mensaje degenerado
     ("hola " × 3000) hizo que el modelo abandonara por completo el esquema
     pedido y devolviera uno inventado (`{"greeting","message","options"}`,
     JSON válido pero irreconocible para el contrato) → como ninguna clave
     coincidía, la respuesta al lead quedaba vacía, sin romper nada pero sin
     contestarle tampoco. Arreglo: nuevo `MAX_INBOUND_MESSAGE_CHARS = 2000`
     en `config.py`, `Zero.converse_result` trunca el mensaje entrante antes
     de pasarlo a CONCIERGE (mismo patrón que ya se usaba para `knowledge`).
     Verificado en vivo: antes, "mensaje_gigante" volvía con `len=0`; después,
     una respuesta normal.
   - 4 tests nuevos (`tests/test_core.py`, `tests/test_contracts.py`
     actualizado). 392/392 tests en verde, en el Mac y en Ubuntu por igual.
4. **Bug real encontrado y arreglado en `zero/discovery.py`** (enriquecimiento
   de decisor) — probado en vivo contra internet real con un ICP nuevo
   ("estudios contables pymes Santiago", sin usar antes) para confirmar que
   el filtrado seguía siendo confiable. Encontró un caso real en gepa.cl: la
   página tiene testimonios de clientes tipo `"...excelente servicio." Roberto
   Fuentes Director, Constructora Fuentes Ltda.` — el extractor de
   nombre+rol capturaba el nombre de la OTRA EMPRESA citada en el testimonio
   (o, en un segundo caso similar sin sufijo legal, el nombre de la persona
   que da el testimonio) como si fuera el decisor de la empresa que se está
   evaluando. Dos capas de arreglo: (a) lista de palabras de razón social
   ("Ltda", "Constructora", "Inmobiliaria", etc.) sumada a `_NOT_NAME`; (b)
   heurística barata — cuando el nombre solo aparece DESPUÉS del rol (sin uno
   inmediatamente antes) y hay una comilla de cierre poco antes en el texto,
   es casi seguro una cita de testimonio, no una ficha de equipo, y se
   descarta. Verificado en vivo: antes del fix, Gepa traía un nombre falso;
   después, ningún nombre (mejor no tener dato que tener uno inventado). 4
   tests nuevos en `tests/test_discovery.py`.

Puntual: **fix de Llamadas.jsx** (2026-07-13) — el botón "Llamar" quedaba
clickeable con las listas de agentes/números de Vapi vacías, disparando una
llamada al backend que ya se sabía que iba a fallar. Ahora se deshabilita con
un tooltip claro. Los mensajes de error nuevos de `place_call` (número vacío,
curl no disponible) ya se mostraban bien sin tocar el frontend — `api.js` ya
extrae el `detail` de cualquier 400 del backend.

392/392 tests en verde tras toda esta ronda.

---

## Plan B (detalle completo)

Motor real (que de verdad SOLUCIONE). El punto 2 (discovery, con un límite
todavía abierto) se quedó en `roadmap.md`, no está acá.

1. **Calificación/score REAL** contra el ICP del cliente — ✅ commit `motor-real`
   (prompts reales + `zero/icp.py` + camino real con parseo a prueba de balas).
3. **Outreach de calidad real** — ✅ evaluado en vivo (2026-07-04) con el modelo
   real (Ollama qwen2.5:7b) contra el lead real de mejor score de la prueba de
   arriba (Splash Piscinas). El mensaje en sí fue sólido (menciona bien
   PoolEdge, el rubro del lead, tono profesional, CTA claro), pero encontró 2
   bugs reales de calidad, ambos arreglados:
   - **Saludo roto**: sin rol/nombre verificado, el modelo saludaba con el
     **email crudo como si fuera un nombre** ("Hola ventas@splash.cl,") — se ve
     robótico y le resta credibilidad al primer contacto. Arreglado con una
     instrucción explícita en `prompts/outreach.md` (saludar a la empresa, nunca
     citar el email/teléfono como nombre).
   - **Rol placeholder citado como real**: incluso en modo mock, un lead con
     `role="por verificar"` (el placeholder honesto de PROSPECTOR cuando no
     hay decisor verificado) generaba mensajes tipo *"vi que lideras como por
     verificar en Splash Piscinas"*. Nueva constante compartida
     `contracts.ROLE_UNVERIFIED`; `outreach.py` y `prospector.py` la tratan
     igual que un rol vacío/desconocido. Test de regresión agregado.
   - **Firma inventada** (encontrada corriendo `main.py` real, tier STARTER, tras
     arreglar los dos bugs de arriba): sin nadie con quién firmar, el modelo
     real firmó literalmente **"Me llamo OUTREACH... Atentamente, OUTREACH"** —
     usó el nombre interno del sub-agente como si fuera una persona, delatando
     el mecanismo a un lead real. Causa: `run_pipeline` nunca le pasaba a
     OUTREACH el vendedor asignado al cliente (Fernanda/Stéfano), a diferencia
     de `converse_result` (CONCIERGE), que sí lo hacía. Arreglado: mismo patrón
     `{name, tone}` de `vendor_for(client_id)` ahora viaja en `data.vendor` para
     OUTREACH también; `prompts/outreach.md` instruye firmar con ese nombre si
     viene, nunca inventar uno, y **nunca usar "OUTREACH" ni ningún nombre de
     agente/rol interno como firma**. Modo mock actualizado para el mismo
     contrato (firma con `data.vendor.name` si viene, sin firma de persona si
     no). 3 tests nuevos (firma con vendor, nunca firma con el nombre del
     agente, integración completa en `run_pipeline`).
   **Bug de mecanismo encontrado y arreglado en el camino**: QUALIFIER con
   backend real (probado con qwen2.5:7b, aplica a cualquier modelo real) a
   veces omitía `channel`/`email`/`phone`/`role` al reescribir el JSON —
   rechazaba leads perfectamente completos por una falla de fidelidad del
   modelo, no por datos faltantes. `_merge_qualifier_scores` en
   `orchestrator.py` restaura todo excepto `score`/`icp_reasons` desde el lead
   original.
   **Auditoría de TRACKER (2026-07-06)** — mismo chequeo que a OUTREACH, ya que
   compartía el mismo hueco (nunca tenía tests dedicados). Encontrado: un bug
   **100% determinista, sin necesitar modelo real** — `name = s.get("name") or
   "Hola"` metía el saludo genérico COMO SI fuera el nombre, produciendo
   *"Hola Hola, te escribí hace unos días..."* para cualquier lead sin nombre
   verificado (el caso más común en discovery web real). También sin
   `data.vendor` (mismo hueco que tenía OUTREACH) — mismo arreglo: vendor
   persona ahora viaja en `run_followups` → TRACKER, `prompts/tracker.md`
   actualizado con las mismas reglas de saludo/firma, subject de "breakup"
   arreglado para no mostrar `"None"` sin nombre. 5 tests nuevos
   (`TrackerTest`, cero tests previos). 345/345 en verde.
   **Auditoría de PITCHWRITER (2026-07-06)** — el redactor del pitch propio de
   ZeroAI (pestaña "Vender", `/api/pitch/generate`), probado en vivo con el
   modelo real. 2 hallazgos:
   - **Firma inventada**, mismo patrón de siempre: cerró "Un saludo,
     PITCHWRITER". Distinto de OUTREACH/TRACKER porque esta herramienta no
     tiene vendor asignado (es el pitch de ZeroAI mismo, lo revisa/edita Diego
     antes de mandar) — el arreglo fue más simple: nunca firmar con un nombre
     de agente/rol, cerrar genérico sin nombre (el mock ya lo hacía bien, cero
     tests previos rotos).
   - **Vendió el servicio equivocado** (más serio): con la nota de contexto
     "vi que están contratando vendedores en LinkedIn" (pensada como gancho de
     apertura), el modelo pivoteó a vender **búsqueda de candidatos**, un
     servicio que ZeroAI no ofrece — confundió el gancho con el producto.
     `prompts/pitchwriter.md` ahora aclara: `notes` es solo la apertura, la
     oferta es siempre leads B2B, nunca cambia según de qué hable la nota.
   - Solo cambio de prompt (el mock ya estaba bien en ambos frentes) — sin
     test de código nuevo, mismo límite que otros fixes de prompt (no se
     puede testear determinísticamente el comportamiento de un modelo real).

Canales reales:

4. **Que al menos un canal ENVÍE de verdad** (email = el más viable) — ✅ **capa de envío
   lista, mock-first**. `zero/channels.py`: abstracción `Outbox` + `MockSender` /
   `EmailSender` (SMTP stdlib) / `WhatsAppSender` (Meta Cloud API). El orquestador envía
   el primer toque (`run_pipeline`) y los follow-ups (`run_followups`); cada envío queda
   en el historial del CRM. **Mock por defecto incluso con credenciales** — se envía de
   verdad solo con `OUTBOX_LIVE=1` (interruptor "Activar envío real" en Config). Cards de
   Email y WhatsApp en el dashboard. 3 tests nuevos.
   **Probado en vivo (2026-07-06)**: SMTP real (Gmail) ya configurado y
   `outbox_live: true` en producción. Confirmado punta a punta con 2 correos
   reales — uno vía `/api/test-email` (send directo) y otro vía el `Outbox`
   real (con reintentos) — ambos llegaron. Falta: el **agente conversacional de
   WhatsApp** (entrante de dos vías, que se apoya en el loop de respuestas).

   **Hallazgo de robustez (no es bug de código, es riesgo operativo):** el
   remitente es una cuenta de **Gmail personal** (`fudyfoodscl@gmail.com`), no
   un dominio propio de negocio. Tres riesgos reales para cuando haya volumen:
   límite de ~500 correos/día en Gmail gratis; mala entregabilidad (sin
   SPF/DKIM de un dominio propio, más probable que cualquier filtro antispam
   lo mande a spam); y riesgo a la cuenta personal si Gmail detecta un patrón
   de envío masivo/frío. La solución completa (dominio propio + proveedor
   dedicado tipo SES/Mailgun) es gasto — ya está en
   "⏸️ Pendientes de PAGO" en `roadmap.md`, no se toca ahora.

   **Arreglado, gratis, en el camino**: el "From" del email salía con la
   dirección pelada de la cuenta SMTP, sin decir de parte de quién escribía —
   mismo problema de fondo que las firmas rotas de OUTREACH (ver arriba).
   `EmailSender` ahora arma el header `From` con el nombre
   del vendedor asignado (ej. "Stéfano <cuenta@gmail.com>") cuando
   `_deliver` (usado por `run_pipeline`/`run_followups`) se lo pasa — mismo
   patrón que ya existía para WhatsApp/CONCIERGE
   (`vendor_for(client_id)`). `_build_message` se separó a `@staticmethod`
   para poder probarlo sin tocar la red. 3 tests nuevos. 340/340 en verde.

Robustez:

5. **Sin crasheos, maneja datos malos** — ✅ parseo tolerante + 40/40 tests.

Operación:

6. **Login / multi-cliente** — ✅ (2026-06-11): gate de un password (`zero/auth.py`,
   tokens firmados por el propio password) + middleware en `api.py`; sin password
   configurado queda abierto (dev).
7. **Loop completo** (respuesta → acción) — ✅ **agente conversacional listo, mock-first**.
   `register_reply` cierra la secuencia y mueve a `replied` (forward-only). Agente
   **CONCIERGE** (`zero/agents/concierge.py` + `prompts/concierge.md`): responde preguntas
   sobre el negocio del cliente usando su ICP, propone reunión, y **se transparenta como
   IA** si le preguntan. `Zero.converse` (redacta) y `Zero.handle_inbound` (mapea entrante
   → cierra loop → responde → envía). WhatsApp entrante: `zero/whatsapp_inbound.py` (parser)
   + webhook `GET/POST /api/webhooks/whatsapp` (verificación Meta + recepción). Probador en
   vivo: `POST /api/whatsapp/simulate` y card **"Probar el agente de respuestas"** en Config
   (mock por intención; con Anthropic key responde el modelo real). **Detección automática
   de respuestas** ✅ (2026-06-11): `zero/inbox.py` (abstracción `Inbox` + `MockInbox` /
   `FileInbox` drop-box / `ImapInbox` stdlib con `INBOX_LIVE=1`). El orquestador corre
   `check_replies()` antes de los follow-ups (`run_followups`): quien ya respondió no
   recibe más toques. Acción `--action replies` y flag `--inbox` en el CLI. **Intents
   ampliados + ofertas pendientes** ✅ (2026-06-11): CONCIERGE maneja objeciones,
   desconfianza y "mándame info" (intents `objection/trust/info`), y ZERO **cumple lo
   que el agente promete**: la oferta queda en `memory.pending_offers` y la aceptación
   del lead ("sí", "por acá", un correo) dispara el envío del resumen real
   (`build_info_summary`, fiel al ICP) por el canal elegido, con evento `info_sent`
   en el CRM. La URL pública ya está resuelta — ngrok
   con dominio fijo (`handpick-monogamy-spiny.ngrok-free.dev`), ver
   `docs/GO-LIVE.md` / `docs/estado-integraciones.md`. Solo falta el número de
   WhatsApp Business real (bloqueado hoy por la verificación de cuenta personal
   de Meta, ver "Estado de infraestructura" en `roadmap.md`).

   **Auditado en vivo (2026-07-06)** con el modelo real (Ollama qwen2.5:7b)
   contra una conversación realista de "pooledge" (precio general, pedido con
   cantidades reales, objeción, desconfianza, cierre de reunión) — con ficha y
   lista de precios reales cargadas. Encontró 2 bugs reales, ambos arreglados:
   - **Cotización mal calculada, en silencio**: pedir "50 metros de borde recto
     y 30 m2 de pastelón antideslizante" calculó qty=1 en vez de 30 para el
     segundo ítem, y descartó el primero por completo — el bloque de números
     mostrado al lead ($11.305) no coincidía ni con la cantidad real ni con el
     propio texto del modelo (que sí había calculado bien, $341.650, violando
     encima la regla de "el LLM nunca hace la aritmética"). Causa raíz en
     `zero/quotes.py::extract_request`: el regex de cantidad exigía el número
     pegado al nombre del ítem, y fallaba con "30 m2 **de** X" (palabra de
     unidad + preposición de por medio). Arreglado: tolera hasta 2 palabras de
     relleno entre el número y el ítem. **Este módulo no tenía NINGÚN test
     hasta hoy** — nuevo archivo `tests/test_quotes.py`, 18 tests.
   - **Nombre de vendedor inconsistente**: en una respuesta el modelo se
     presentó como "Fernanda" aunque el vendedor asignado a "pooledge" era
     Stéfano — copió el nombre literal de los ejemplos de calibración del
     prompt en vez de sustituirlo por `data.vendor.name` (la instrucción para
     sustituirlo ya existía, pero un modelo chico a veces imita el ejemplo
     literal). Arreglado: los ejemplos ahora usan `{NOMBRE}` como placeholder
     explícito en vez de un nombre real plausible ("Fernanda"), con aviso
     reforzado de que es una variable, no texto a copiar.
   - También se reforzó la regla de "cero montos" en `prompts/concierge.md`
     con una prohibición explícita de que el modelo haga la aritmética por su
     cuenta, "aunque le parezca fácil".

---

## Plan A - Pulido del dashboard
1. **Pulido en TODAS las páginas** (animaciones, skeletons, estados carga/error/vacío) — ✅
   commiteado (rework en las 9 vistas del frontend).
2. **Drag & drop en el Pipeline** — ✅ presente en `frontend/src/pages/Pipeline.jsx`.
3. **Formulario de ICP en "Buscar leads"** — ✅ en `frontend/src/App.jsx`; el backend
   `/api/pipeline` acepta `icp`.
4. **Búsqueda + filtros en Leads** — ✅ en `frontend/src/pages/Leads.jsx`.

## Integraciones y dashboard de configuracion
Panel `IntegrationCard` en `frontend/src/pages/Config.jsx` + endpoint `/api/config`
(`api.py`), guarda keys en `.env` local, nunca devuelve el secreto. Integraciones:
- **Anthropic** (modo `--live`) · **ElevenLabs** (voz) · **Vapi** (llamadas) ·
  **Supabase** (CRM en la nube).
