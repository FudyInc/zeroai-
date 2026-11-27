# Plan de acción ZeroAI — 2026-11-27

Junta dos decisiones de Diego del 27-11:
1. **El agente de WhatsApp plug-and-play es EL producto.** Después: contenido de marketing por
   empresa (campañas, reels, videos) y agentes de llamada. Los leads (más B2C que B2B) pasan
   a ser un extra del paquete.
2. **Conectores:** que el agente pueda leer los sistemas del cliente sin depender de que cada
   uno tenga API propia. Decisión: construir YA la puerta única ("fuente de datos del
   cliente"); MCP entra como segunda fuente cuando un cliente real lo necesite.

Vara de todo el plan: **horas desde que un negocio firma hasta que su agente responde bien.**
Hoy son días de trabajo de Diego (PoolEdge = reglas a mano en `zero/losetas_*.py`).

Restricciones: cero gasto (sin Supabase Pro), equipo de 1, solo-stdlib en el núcleo, nada se
borra (mover a `~/respaldos/` en vez de borrar).

---

## Fase 0 — Estabilizar (esta semana; nada necesita Supabase)

| # | Qué | Quién | Hecho cuando |
|---|---|---|---|
| 0.1 | Aislar los tests (Supabase y `GROQ_API_KEY` reales) | CORE | suite verde en `/home/diego/zeroai` con su `.env` real |
| 0.2 | `make_crm` cae a `crm.json` si Supabase falla | CORE | test del 402 verde; CRM del dashboard sin 503 |
| 0.3 | Login local de emergencia (`users.json`, hash, gitignorado) | CORE | Diego entra al dashboard con Supabase en 402 |
| 0.4 | Medir y cortar el egress (`app_state` completo por request) | CORE | lecturas por request contadas en un test; egress confirmado en el panel |
| 0.5 | Respaldo diario fuera del PC (state, crm, sqlite de WhatsApp) | CORE/OPS | copia fechada en Drive, con aviso si falla |
| 0.6 | Política de privacidad corregida (formularios SÍ van al backend) | LANDING | `web/privacidad.html` coincide con `web/script.js` |
| 0.7 | Mover `crm.json` de `zero-core`/`zero-motor-whatsapp` a `~/respaldos/` | AUDIT | **requiere OK de Diego**; la tanda corre sin abortar |
| 0.8 | Subir `fix/avisos-sin-mail-fudy` (`6ebca28`) y PR a main | AUDIT | **requiere OK de Diego**; prod vuelve a main |
| 0.9 | Reescribir la misión en `CLAUDE.md` y `01 - Vision.md` | AUDIT/PROMPTS | ya no dice "leads B2B" como centro |

## Fase 1 — WhatsApp plug-and-play (semanas 2–4)

| # | Qué | Quién | Hecho cuando |
|---|---|---|---|
| 1.1 | **Puerta única "fuente de datos del cliente"**: todo lo que el agente consulta del negocio (catálogo, precios, stock, FAQ, horarios) pasa por una interfaz; la importación por archivo de PR #31 es la primera implementación, con mock | CORE | el motor no lee la ficha ni los precios por otro camino (grep lo demuestra) |
| 1.2 | Inventario de `zero/losetas_*.py`, `pool_border.py`, `pooledge_credit.py`: qué es DATO del negocio (va a la fuente) y qué es LÓGICA reutilizable (cotizador genérico) | MOTOR | lista escrita; sin mover código todavía |
| 1.3 | Pantalla de onboarding del dashboard (pedido DASHBOARD-2 del 22-11, aún no en main) | DASHBOARD | un negocio sube su archivo y ve la lista de chequeo |
| 1.4 | Ensayo de punta a punta con un negocio ficticio nuevo, cronometrado | QA | número de horas registrado = la vara |
| 1.5 | Canal oficial: estado del WABA en Meta; plan si se banea el número de whatsapp-web.js | Diego | decisión escrita |

## Fase 2 — Vender (en paralelo desde la semana 2)

| # | Qué | Quién | Hecho cuando |
|---|---|---|---|
| 2.1 | Landing reescrita alrededor del agente de WhatsApp; fuera "12 reuniones", "4 canales" y la FAQ de precio por consumo | LANDING | ningún claim sin dato que lo respalde |
| 2.2 | Calendly: `booking_url` en el perfil de `zeroai` + botón "Agenda 15 min" | CORE + LANDING | **requiere el link de Diego** |
| 2.3 | Primer cliente externo que pague (piloto con precio, fecha y monto registrados) | Diego | ingreso registrado |
| 2.4 | Métricas antes/después de ese cliente (tiempo de respuesta, conversaciones, ventas atribuidas) | CORE/DASHBOARD | vista con dato crudo |

## Fase 3 — Pitch (cuando haya 1 cliente pagando + 30 días de métricas)
One-pager, deck, unit economics (costo por conversación y por cliente al mes), demo grabada,
análisis legal mínimo (Ley 19.628 / 21.719 y uso de WhatsApp), equipo y participación.

## Aparcado, con condición de activación
| Idea | Se activa cuando |
|---|---|
| Conectores MCP (segunda implementación de la puerta 1.1; solo lectura, lista blanca por cliente, escrituras con aprobación humana) | un cliente real necesita un dato en vivo que el archivo no cubre (stock, estado de pedido) |
| Contenido de marketing por empresa (campañas, reels, videos) | un cliente de WhatsApp pagando lo pide, o fase 1 cerrada |
| Agentes de llamada | hay saldo para voz/número y un cliente que lo pida |
| Leads como extra del paquete (B2C) | fase 2 cerrada |
| Supabase Pro | hay ingreso que lo pague |
