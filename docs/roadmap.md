# Roadmap / estado de los planes — ZeroAI

Fuente de verdad de en qué vamos. Recuperado de los transcripts de sesión y
verificado contra el código (2026-06-07). Si trabajamos un plan, **se anota aquí
en el momento** — así una compresión de contexto no nos lo borra.

---

## 🔴 Estado de infraestructura (2026-07-03) — dónde vive cada cosa

- **Rama de producción: `main`.** `chore/terminales-por-rol` (la que de verdad corría
  en Ubuntu) se fusionó acá vía fast-forward. Las ramas de trabajo (`core`, `dashboard`,
  `prompts`, etc.) se fusionan y se **borran** — no se acumulan durante semanas. Ver
  [[zero-branch-sprawl-lesson]]: hoy mismo aparecieron un proyecto de Vercel duplicado y
  un `GET /api/vendors` construido dos veces por tener demasiadas ramas divergiendo.
- Nota de modelo de negocio (ver sección de escalabilidad más abajo): el dashboard es
  **propietario** — solo ZeroAI lo opera, los clientes nunca entran ahí.
- **Frontend:** un solo proyecto en Vercel — **`zeroai`** (`zeroai-six.vercel.app`),
  conectado por Git a `main` (auto-deploy en cada push). Nunca correr `vercel`/
  `vercel --prod` manual desde ningún checkout — eso fue lo que generó los duplicados
  `zeroai-x16d`, `zeroai-dashboard` y `project-qfwaa` (ya borrados/por borrar).
- **Backend:** corre en el PC Ubuntu como dos servicios `systemd`
  (`zero-backend.service` + `zero-tunnel.service`), arrancan solos al prender el PC y se
  reinician solos si se caen. Expuesto vía túnel fijo de ngrok (dominio "dev domain,
  yours forever" — gratis, no cambia entre reinicios). `VITE_API_URL` en Vercel apunta a
  esa URL.
- **Antes de construir un endpoint nuevo:** revisa el `api.py` real (rama `main`)
  primero con `grep` — no asumas el contrato de un prompt sin verificar contra el código.
- Guardia automática: `tests/test_core.py::ApiRoutesTest` falla si `api.py` registra la
  misma ruta dos veces (justo el problema de hoy).
- **Motor real (Ollama local) — ya activo en producción, verificado 2026-07-06.**
  `LOCAL_MODEL`/`LOCAL_MODEL_URL` ya estaban seteados en el `.env` del Ubuntu (no
  hizo falta tocar nada) y `api.py::_agents_best()` ya prioriza local sobre mock
  cuando no hay `ANTHROPIC_API_KEY` — confirmado con `GET /api/config` mostrando
  `local_model` y con `POST /api/whatsapp/simulate` devolviendo `"mode": "live"`.
  **Latencia real medida** (3 llamadas a CONCIERGE vía el endpoint real, en el
  Ryzen 7 9700X sin GPU): **~35s en frío** (modelo recién cargado en RAM por
  Ollama tras estar inactivo) y **~7-9s en caliente** (llamadas seguidas).
  **Resuelto (2026-07-06)**: `OLLAMA_KEEP_ALIVE=30m` vía override de systemd en
  el servidor (`/etc/systemd/system/ollama.service.d/override.conf`, ver
  `docs/motor-real.md`) — sube el default de 5 a 30 minutos antes de descargar
  el modelo de RAM, gratis, sin tocar código. Verificado en vivo con
  `GET /api/ps` (`expires_at` confirmado a 30 min). **Hallazgo importante en el
  camino**: el campo `keep_alive` por request NO funciona vía
  `/v1/chat/completions` (el endpoint compatible con OpenAI que usa
  `LocalBackend`) — solo la API nativa de Ollama lo respeta; por eso el fix es
  a nivel de servidor, no de código.
  **Rescatado de código sin commitear** (2026-07-06) — al limpiar las carpetas
  duplicadas viejas en Ubuntu (`/home/diego/zero`, `/home/diego/zeroai-`, ver
  [[zero-branch-sprawl-lesson]]) apareció trabajo válido nunca subido a `main`:
  `--local-timeout` en el CLI (override opcional; el default sigue siendo el
  600s ya generoso de `LocalBackend`) y `no_think` — para modelos razonadores
  (DeepSeek-R1, QwQ; Diego tiene `deepseek-r1:7b` instalado) le pide a Ollama
  que se salte el bloque de razonamiento (parámetro `think`, Ollama 0.9+).
  **Verificado en vivo (2026-07-06)** contra `deepseek-r1:7b` real: sin el
  flag, 97 tokens de razonamiento (en un campo `reasoning` aparte — no
  embebido en el texto como se pensó al principio); con el flag, solo 10 —
  ahorro real de tiempo/tokens, no un fix de parseo. Sin efecto en qwen2.5
  (el que usa hoy). 2 tests nuevos. El resto de lo encontrado ahí
  (scripts viejos de terminales Ptyxis, superados por los workspaces de
  Conductor) se descartó, sin valor. Ambas carpetas (`/home/diego/zero`,
  `/home/diego/zeroai-`) ya se **borraron** del Ubuntu — solo queda
  `/home/diego/Desktop/zeroai`, la que corre de verdad (systemd).
- **Supabase real conectado (2026-07-09)** — Diego decidió activarlo ya que hay
  plata real en juego (Vapi, ElevenLabs) y quiere las keys respaldadas.
  Proyecto viejo **"zeroai-estudio-latam"** estaba `INACTIVE` (el plan gratis
  lo pausó solo tras no usarse — confirma el riesgo real, no solo teórico).
  Diego aclaró que ese proyecto es de otra cosa, así que se creó uno **nuevo y
  dedicado, "zeroai"** (`lhdvybpgyexxypjtthce.supabase.co`, org FudyInc,
  `sa-east-1`, plan gratis $0/mes). Se corrió `supabase_schema.sql`
  (`crm_leads` + `app_state`) con **RLS activado desde el día 1** (el backend
  usa la key `service_role`, que ignora RLS igual — cero riesgo de romper
  nada, cero costo, solo más seguro por defecto). Se migraron los **22 leads
  reales** de `crm.json` y todo `state.json` (clientes, ICP, secuencias,
  vendedores) del Ubuntu de producción al proyecto nuevo — confirmado
  funcionando de punta a punta sobre HTTP real (`/api/clients`, `/api/kpis`,
  `/api/leads`, `/api/vendor`, `/api/knowledge`, todos leyendo de Supabase).
  **Resuelto (2026-07-13):** las 2 tablas vacías con forma de ZeroAI que habían
  quedado en el proyecto viejo no se tocan — Diego confirmó que ese proyecto
  ("zeroai-estudio-latam") es de otra cosa suya, no de este repo. Solo se
  trabaja en el proyecto **"zeroai"** (`lhdvybpgyexxypjtthce`); ver
  [[zero-supabase-testing]].
  **Keep-alive diario**: nuevo `scripts/supabase_keepalive.py` (GET liviano a
  `app_state`) + `zero-supabase-keepalive.service`/`.timer` en systemd
  (corre todos los días 9am, `Persistent=true` para no perderse si el PC
  estaba apagado) — para que el plan gratis nunca vuelva a pausarse por
  inactividad. Probado en vivo, responde OK.
  **Límite honesto**: ningún código evita que alguien borre el proyecto a
  mano desde el panel de Supabase, ni protege contra un cambio de política
  del plan gratis — eso depende de que la cuenta de Diego esté segura (2FA).
- **Vapi conectado (2026-07-09)** — API key (privada, nunca por chat, siempre
  vía Configuración → tarjeta Vapi) guardada y activa (`vapi: true` en
  `/api/config`). El frontend (`Llamadas.jsx`) ya arma el +56 de Chile
  automático — sin cambios de código, solo faltaba la cuenta.
- **Todas las terminales respaldadas en GitHub (2026-07-09)** — se encontró
  trabajo real sin subir en varias: `dashboard` (2 archivos sin commitear +
  la rama nunca pusheada), `landing` (la primera versión completa de la
  landing, ni siquiera agregada a git), `debug` e
  `investigacion-mercado-competencia` (commiteadas pero nunca pusheadas).
  Las 4 quedaron commiteadas y subidas a GitHub con upstream configurado.
  `core` se sincronizó (tenía 11 commits de atraso). Ninguna de las 3
  terminales de MOTOR tenía trabajo propio todavía. 366/366 tests en verde
  después de sincronizar todo.

## 🎯 Plan de fiabilidad — "listo para el mercado" (2026-07-04) · 🟡 EN CURSO
Criterio: no lanzar hasta que esto esté resuelto **de verdad**, no "se siente
listo". Detalle completo de cada punto (bugs encontrados, causa raíz, archivos,
tests) en [docs/roadmap-archive.md](roadmap-archive.md#plan-de-fiabilidad-detalle-completo).

**Abierto:**
2. **Fragilidad del hosting** — ⏸️ PAUSADO A PROPÓSITO. El backend depende de un
   PC Ubuntu + túnel gratis de ngrok; si se apaga/reinicia sin querer, todo el
   producto cae. Decisión de Diego: mientras esté en fase de desarrollo/prueba,
   sin clientes reales, esto queda pausado (ni VPS, ni UptimeRobot todavía). Plan
   ya definido para cuando toque retomarlo (VPS barato, monitoreo con alerta,
   BIOS "Restore on AC Power Loss") — detalle en el archivo.

**Cerrado** (✅, detalle en el archivo):
1. Plantillas de WhatsApp Business — código listo; falta el paso manual de Diego
   (crear la plantilla en Meta Business Manager, esperar aprobación).
3. Test end-to-end HTTP real (`tests/test_api_http.py`) — encontró y arregló un
   500 crudo cuando Supabase no respondía.
4. Checklist de fiabilidad (firma del webhook, reintentos de envío, backup de
   crm.json/state.json con rotación `.bak` — incluye un simulacro real de
   corrupción en Ubuntu de producción —, casos difíciles de CONCIERGE,
   expiración de sesión) — todo hecho y probado.
   Auditorías en vivo por agente/módulo con el modelo real — ANALYST (sin bugs,
   solo un hallazgo de calibración), MOTOR-llamadas, defensivo/webhooks/
   discovery, y CONCIERGE por WhatsApp — encontraron y arreglaron 6 bugs reales:
   `intent` de CONCIERGE perdido en silencio, `AttributeError` en el webhook de
   WhatsApp y en `list_assistants`/`metaads` si Vapi/Meta cambia de forma, falso
   positivo de nombre en `discovery.py` (testimonios de clientes), y un mensaje
   gigante que dejaba al lead sin respuesta.

392/392 tests en verde.

---

## Plan A — Pulido del dashboard · ✅ COMPLETO
Los 4 puntos (pulido de las 9 vistas, drag & drop en Pipeline, formulario de ICP
en "Buscar leads", búsqueda + filtros en Leads) — detalle en
[docs/roadmap-archive.md](roadmap-archive.md#plan-a---pulido-del-dashboard).

## Integraciones + dashboard de configuración · ✅ COMPLETO
Panel `IntegrationCard` en Config + `/api/config` (Anthropic, ElevenLabs, Vapi,
Supabase) — detalle en
[docs/roadmap-archive.md](roadmap-archive.md#integraciones-y-dashboard-de-configuracion).

## Plan B — Motor real / "listo para el día 1" (checklist de 7) · 🟡 EN CURSO
Motor real (que de verdad SOLUCIONE). Detalle completo de cada punto (bugs
encontrados, causa raíz, archivos, tests) en
[docs/roadmap-archive.md](roadmap-archive.md#plan-b-detalle-completo).

**Abierto:**
2. **Discovery real** — 🟡 parcial: `DuckDuckGoSource` sin key mejoró harto
   (minería de directorios, extracción de decisor, filtrado de falsos
   positivos), pero **falta un proveedor con key para cobertura mayor**. Límite
   conocido y cuantificado en vivo: contra "pooledge" (piscinas), 8/8 empresas
   reales encontradas, 0/8 sobre el mínimo de calificación por falta de decisor
   verificable en sitios de PyMEs chicas — no es un bug, es el techo del
   scraping sin key. Por eso el piso de calificación es por tier
   (`MIN_ICP_SCORE_BY_TIER`), no un número único — decisión de negocio de Diego,
   no algo que el scraping deba resolver solo.

**Cerrado** (✅, detalle en el archivo):
1. Calificación/score real contra el ICP.
3. Outreach de calidad real — evaluado en vivo, 3 bugs de calidad encontrados y
   arreglados (saludo con email crudo, rol placeholder citado como real, firma
   inventada con el nombre del agente — mismo patrón arreglado después en
   TRACKER y PITCHWRITER). De paso: bug de QUALIFIER perdiendo campos con el
   modelo real, arreglado con `_merge_qualifier_scores`.
4. Canal de envío real (email) — probado en vivo con SMTP real (Gmail), 2
   correos reales confirmados punta a punta. Riesgo operativo anotado: cuenta
   Gmail personal, no dominio propio (límite de envío + entregabilidad) —
   solución completa es gasto, en "Pendientes de pago" más abajo.
5. Sin crasheos, maneja datos malos.
6. Login / multi-cliente.
7. Loop completo (respuesta → acción, CONCIERGE) — auditado en vivo dos veces
   (2026-06-11 y 2026-07-06), encontró y arregló 4 bugs en total (cotización mal
   calculada, nombre de vendedor inconsistente, y los 2 de la ronda de WhatsApp
   más arriba). Falta el número de WhatsApp Business real (bloqueado por
   verificación de cuenta personal de Meta, ver "Estado de infraestructura").

## Formulario de ICP (mejorado, 2026-06-07)
Antes capturaba 4 de 8 campos y era write-only. Ahora: los **8 campos** (`industry,
sells, buyer_roles, company_size, regions, must_have, exclude, context`) en el modal
"Buscar leads"; endpoint `GET /api/icp?client=` y **precarga del ICP guardado** del
cliente al abrir el panel (+ link "↻ cargar guardado"). El ICP se persiste por cliente
en `state.json` (local) — pasarlo a la nube es parte de multi-tenant (#6).

---

## Escalabilidad + multi-tenant (track combinado, 2026-06-07) · ✅ COMPLETO
Modelo decidido: **agencia, un solo dueño** (tú entras; los "clientes" son cuentas
internas aisladas en datos, no entran ellos).
1. **Lectura escalable** — ✅ `SupabaseCRM` ya no hace `SELECT *`: carga **por cliente**
   (`_ensure`), `client_ids()` por proyección, `find_by_contact` server-side; `crm.list`
   con `limit/offset`. `/clients` y `/kpis` scoped. 53/53 tests.
2. **Auth (un login de agencia)** — ✅ (2026-06-11): ver Plan B #6.
3. **Estado a la nube** — ✅: `SupabaseMemory` (`zero/memory_supabase.py`) guarda el
   snapshot completo (ICP, secuencias, ofertas pendientes) en `app_state`;
   `make_memory` la usa si hay credenciales y cae a `state.json` local si no.
4. **Paginación fina** — ✅ (2026-06-08): `CRM.query(client, stages, limit, offset)` empuja
   filtro+orden+slice a PostgREST; `/api/leads?group&limit&offset` → `{leads,total}`;
   frontend con `useInfiniteQuery` + "Cargar más". Orden con desempate único (lead_key)
   para páginas estables.
5. **ICP en la nube** — ✅ verificado (2026-06-08): tabla `app_state` creada, `SupabaseMemory`
   activo, roundtrip de ICP confirmado.

## Meta Ads / Campañas (2026-06-08) · 🟡 mock-first
`zero/metaads.py` (MockMetaAds + MetaAds real vía Graph + `make_metaads`), `/api/campaigns`,
pestaña **Campañas** (KPIs gasto/leads/CPL + tabla + filtro), card en Config. Mock por
defecto; real con `META_ADS_TOKEN` + `META_AD_ACCOUNT_ID`. **Atar leads de ads → CRM: ✅**
(`Zero.import_ad_leads`, endpoint `POST /api/campaigns/sync-leads`, botón en la pestaña
Campañas; entra como `qualified` + tag "Meta Ads", mock por defecto). Falta: insights
reales (gasto/leads del endpoint de Meta).

## ⏸️ Pendientes de PAGO (hacer cuando Diego pueda pagar — ver [[zero-cost-policy]])
Cero gasto salvo lo que Diego ya decidió activar (Vapi, Supabase — ver abajo).
Todo esto está construido **mock-first / con seam listo**; solo falta
enchufar la cuenta/key de pago para que funcione de verdad:
- **Motor real con Anthropic** — calidad real de scoring/mensajes/agentes. (Alternativa
  gratis: modelo local Ollama).
- **Meta Ads real**: insights (gasto/leads/CPL reales) y gestión que **aplica** el plan
  de Claude (pausar/presupuesto). (La cuenta de Meta nueva además tiene cooldown inicial.)
- **Discovery con proveedor con key** — cobertura real de prospección (ver Plan B #2).
- **ElevenLabs** (clonación de voz) — key ya cargada, pero la función de voz
  (`zero/voice.py`) sigue sin enchufarse al producto (solo CLI standalone hoy).
- **Envío email/WhatsApp a volumen** (deliverability / proveedor dedicado tipo SES).

**Ya conectado (no está pendiente):** Vapi (llamadas salientes, `/api/call` real
vía dashboard) y Supabase (CRM/estado en la nube, proyecto "zeroai") — activados
por decisión explícita de Diego pese a la política de cero gasto.

## Lo que sigue (recomendación)
Mientras no haya más pagos: perfeccionar lo gratis. Rework visual del dashboard
y la landing pública en curso, cada uno en su propia terminal (dashboard /
landing). Backend: sin frentes de auditoría abiertos por ahora — ver
"Pendientes de PAGO" arriba para lo que falta con presupuesto.

## Pendiente de diseño — dashboard a monocromo (anotado 2026-07-13, no hacer aún)
El rework visual del dashboard (Card/Button/Eyebrow/SectionTitle, paleta slate/pewter/
champagne gold) está completo en las 12 páginas. Queda una decisión de diseño abierta,
**no un bug**: el gráfico de barras del Dashboard y las columnas del Kanban/Leads usan
colores **semánticos por etapa** (verde=ganado, rojo=descartado, etc.), no monocromo
puro. Se dejó así a propósito porque esos colores codifican datos reales. Si en algún
momento se quiere más fiel al monocromo, la opción es llevarlos a una escala slate/gold
y diferenciar etapas solo por ícono o posición — pero es a demanda, Diego pidió
explícitamente no tocarlo todavía.
