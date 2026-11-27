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

Revisada tras la auditoría del cómo (`FudyInc/AUDIT:docs/auditoria/2026-11-27-como.md`).

| # | Qué | Quién | Hecho cuando |
|---|---|---|---|
| 1.0 | Meter al repo el sync ventas→Excel que corre fuera de git (`~/.local/lib/pooledge-excel/`) | CORE | vive en `scripts/` con tests; el servicio apunta al repo |
| 1.0b | **Decisión de Diego (27-11): PoolEdge sigue en Opus 5.5** ("Sonnet no es lo suficientemente poderoso para negocios"). Queda: que el registro de consumo llegue al log (hoy `logging.info` en `losetas_agent.py:421` no aparece en `journalctl`) para conocer el costo real por cliente al mes — dato para precios y unit economics; y aviso de saldo bajo antes de que el agente quede mudo | CORE | costo diario visible; aviso probado en su modo de fallo |
| 1.1 | **Puerta única** `zero/client_data.py`: `knowledge() faq() catalog() price() stock() rules()`; `MemoryClientData` envuelve lo de hoy + mock. Cambiar SOLO las lecturas (~12 puntos en `orchestrator.py`) | CORE | suite verde sin cambio de comportamiento; grep: el motor no lee ficha/precios por otro camino |
| 1.1-b | **MCP como fuente de datos**: cliente MCP HTTP stdlib, solo lectura, detrás de `stock()`/`price()`, con la herramienta del cliente mapeada en config (el modelo NO elige herramientas). Servidor MCP falso en tests; URL validada (https, sin IPs privadas, sin redirecciones); secretos en `client_integrations`; interruptores por herramienta en `memory.clients[cid]`; registro `memory.log("mcp_tool_call")`; los guardias aceptan el dato de la herramienta como evidencia | CORE | un cliente de prueba responde stock real desde un MCP falso, de punta a punta |
| 1.2 | Pasar constantes de PoolEdge (`config.py:167-232`, `losetas_*.py`) a `rules()`/`catalog()`, de a una | MOTOR | baja el conteo de `"losetaschile"` en `orchestrator.py` (hoy 42) |
| 1.3 | Grupo de revisión POR CLIENTE (hoy cableado a PoolEdge, `orchestrator.py:2501`) — es la superficie del dueño | CORE | un cliente nuevo recibe sus avisos en su grupo |
| 1.4 | "Demanda real": `knowledge_gaps` cuenta clientes distintos y no pierde historial al resolver; se ve en el dashboard | CORE + DASHBOARD | la tarjeta dice "N clientes distintos" |
| 1.5 | Pantalla de onboarding (DASHBOARD-2 del 22-11) | DASHBOARD | un negocio sube su archivo y ve la lista de chequeo |
| 1.6 | Ensayo cronometrado con un negocio ficticio nuevo | QA | horas registradas = la vara |
| 1.7 | Canal oficial: estado del WABA; plan si se banea el número | Diego | decisión escrita |

## Fase 2 — Vender (en paralelo desde la semana 2)

| # | Qué | Quién | Hecho cuando |
|---|---|---|---|
| 2.1 | Landing reescrita alrededor del agente de WhatsApp; fuera "12 reuniones", "4 canales" y la FAQ de precio por consumo | LANDING | ningún claim sin dato que lo respalde |
| 2.2 | Calendly: `booking_url` en el perfil de `zeroai` (ojo: `set_agent_profile` reemplaza el perfil entero, `api.py:2850`) + botón "Agenda 15 min" | CORE + LANDING | **requiere el link de Diego** |
| 2.3 | Primer cliente externo que pague (piloto con precio, fecha y monto registrados) | Diego | ingreso registrado |
| 2.4 | Métricas antes/después de ese cliente (tiempo de respuesta, conversaciones, ventas atribuidas) | CORE/DASHBOARD | vista con dato crudo |

## Fase 3 — Pitch (cuando haya 1 cliente pagando + 30 días de métricas)
One-pager, deck, unit economics (costo por conversación y por cliente al mes), demo grabada,
análisis legal mínimo (Ley 19.628 / 21.719 y uso de WhatsApp), equipo y participación.

## Aparcado, con condición de activación
| Idea | Se activa cuando |
|---|---|
| Agente que ELIGE herramientas MCP (bucle tool_use) y escrituras en sistemas del cliente | un cliente necesita algo que el mapeo fijo de 1.1-b no cubre; hay saldo de Claude |
| Recordatorio proactivo de presupuesto (pedido 05-11) | hay aprobación humana en el grupo; riesgo de baneo evaluado con whatsapp-web.js |
| Instagram comentario → DM | App Review de Meta aprobado |
| Contenido de marketing por empresa (campañas, reels, videos) | un cliente de WhatsApp pagando lo pide, o fase 1 cerrada |
| Agentes de llamada | hay saldo para voz/número y un cliente que lo pida |
| Leads como extra del paquete (B2C) | fase 2 cerrada |
| Supabase Pro | hay ingreso que lo pague |
