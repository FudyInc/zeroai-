# PRD — Base de conocimiento por empresa

**Estado:** revisión parcial · 2026-10-06. Se verificaron los puntos indicados abajo
contra el código y se leyó el almacén Supabase del servicio activo. El flujo de
conversación con la versión integrada aún no se comprobó en producción.
**Contexto:** ZERO se despliega en distintas empresas. Cada una necesita que el agente
sepa *su* negocio. Este documento define qué existe hoy, qué falta y en qué orden.

---

## 1. El problema

Un agente que no sabe del negocio improvisa. Improvisar frente a un lead real es peor
que no contestar: inventa precios, promete lo que no hacemos y quema el contacto.

La ficha de la empresa es lo que separa "un chatbot" de "un vendedor de esta empresa".
Y como ZERO se instala en empresas distintas, **la ficha no puede vivir en el código**:
tiene que ser dato por cliente, cargable sin tocar el repo.

## 2. Qué YA existe (auditado el 2026-08-21 — no reconstruir)

| Pieza | Dónde | Estado |
|---|---|---|
| Ficha por cliente (texto libre) | `memory.set/get_client_knowledge` | ✅ funciona |
| ICP por cliente (estructurado) | `zero/icp.py` + `memory.set/get_client_icp` | ✅ funciona |
| Lista de precios por cliente | `memory.set/get_client_pricing` + `zero/quotes.py` | ✅ funciona |
| Persona del vendedor | `zero/vendors.py` | ✅ funciona |
| Endpoints | `GET/POST /api/knowledge`, `/api/icp` | ✅ funcionan |
| UI de carga | `KnowledgeCard` en `frontend/src/pages/Whatsapp.jsx` | ✅ funciona |
| La ficha llega al agente | `orchestrator.reply_to_inbound` → `data.knowledge` | ✅ funciona |
| Almacén multi-empresa | Supabase (`SupabaseMemory`), archivo local como respaldo | ✅ funciona |

**La arquitectura multi-empresa ya está.** Cada cliente es un `client_id` con su ficha,
su ICP, su catálogo y su vendedor. Instalar ZERO en una empresa nueva no requiere código.

## 3. Qué falta (los huecos reales)

### 3.1 El agente no sabía que la ficha existía — CERRADO
`prompts/concierge.md` declaraba `icp` como "tu única fuente de verdad" y no mencionaba
`knowledge`, aunque el orquestador ya lo pasaba. Con motor local (qwen2.5:14b) el modelo
ignoraba la ficha y contestaba genérico. Corregido el 2026-08-21.

### 3.2 El catch-all de mensajes nuevos apunta a ZeroAI — CERRADO EN CÓDIGO
`config.DEFAULT_INBOUND_CLIENT_ID = "zeroai"` (verificado el 2026-10-06).
La ficha activa de ZeroAI en Supabase coincide con la versionada; el enrutamiento
de una conversación real con este código sigue pendiente.

### 3.3 Un número por empresa — PARCIALMENTE COMPROBADO
`_resolve_inbound_client` sabe resolver la empresa por el número que recibió el mensaje,
si el vendedor tiene `whatsapp_phone_id` asignado. El 2026-10-06 se comprobó sin
mostrar identificadores que ZeroAI usa el número Meta global y que su vendedor
tiene un ID semilla antiguo en el almacén; el código ignora ese ID para enviar.
PoolEdge no está registrado como cliente activo. Antes de conectarlo hay que
asignar y probar su receptor: dos empresas que comparten número requieren
resolver el contacto sin ambigüedad.

### 3.4 La ficha activa puede diferir de la versionada — ABIERTO
La carga por dashboard escribe en el almacén configurado (Supabase o archivo local)
y conserva versiones allí, pero no modifica `docs/ficha-zeroai.md`. El archivo
versionado y `scripts/cargar_empresa.py` permiten reconstruir la ficha, pero cargarlo
sin revisar podría pisar una edición posterior hecha en el dashboard. El comparador
de solo lectura `scripts/verificar_ficha.py --empresa zeroai` detecta diferencias.
La ficha activa y la versionada de ZeroAI coincidieron el 2026-10-06 (3982
caracteres); hay que repetir esa comparación tras futuras ediciones del dashboard.

### 3.5 Límite de 4000 caracteres — ACEPTADO POR AHORA
`reply_to_inbound` corta la ficha en 4000 caracteres para no reventar el contexto. Sirve
para una ficha bien escrita; no sirve para un catálogo largo o un manual. Cuando una
empresa lo necesite, la respuesta NO es subir el límite (más contexto = más lento y más
caro en un modelo local), sino recuperar solo los trozos relevantes al mensaje.

## 4. Qué NO vamos a hacer

- **No vectores ni RAG todavía.** Un índice semántico agrega una dependencia, un proceso
  de indexación y una fuente de fallas nueva, para un problema que hoy no tenemos: 3000
  caracteres de ficha bien escrita rinden más que un RAG mal armado. Se reevalúa cuando
  una empresa real no quepa en el límite.
- **No una ficha por agente.** Una ficha por empresa, compartida por todos sus agentes.
  Dividirla multiplica los lugares donde una verdad puede quedar desactualizada.
- **No autocompletar la ficha con un LLM.** Una ficha inventada por un modelo es
  exactamente el problema que la ficha existe para resolver.

## 5. Orden de trabajo

1. La ficha activa de ZeroAI en Supabase coincidió con `docs/ficha-zeroai.md` el
   2026-10-06. Repetir la comparación antes de una futura carga; el almacén local
   de este checkout no representa producción.
2. `DEFAULT_INBOUND_CLIENT_ID` apunta a `zeroai` en el código. Desplegar la
   versión integrada y comprobar el enrutamiento en una conversación real.
3. Asignar `phone_id` por vendedor cuando haya una segunda empresa en producción. *(3.3)*
4. Exportar ficha del dashboard → repo. *(3.4)*
5. Recuperación por trozos, solo si una empresa real no cabe. *(3.5)*

## 6. Cómo se sabe que funciona

- Un mensaje entrante de un desconocido se contesta con el negocio correcto.
- El agente responde una pregunta específica del negocio usando la ficha, no
  generalidades.
- Preguntado por precios, no inventa cifras (las calcula `quotes.py` o deriva a llamada).
- Instalar una empresa nueva no requiere tocar código: ficha + ICP + catálogo + vendedor.
