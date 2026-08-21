# Otros

Módulos, integraciones y decisiones que no encajan en las notas principales. Fuente: el código en `zero/` y `api.py`.

## Módulos del repo no cubiertos arriba

| Módulo | Qué hace |
|---|---|
| `zero/discovery.py` | `DiscoverySource` · `DuckDuckGoSource` — discovery web real, sin key. Fuente intercambiable (un proveedor con key entra con la misma firma). |
| `zero/icp.py` | Normaliza el ICP del cliente (perfil de cliente ideal) usado por el QUALIFIER. |
| `zero/channels.py` | `Outbox` con `MockSender` / `EmailSender` (SMTP) / `WhatsAppSender` (Meta Cloud API). `OUTBOX_LIVE=1` para enviar de verdad. |
| `zero/calls.py` | Llamadas de voz vía **Vapi** (usa `curl` del sistema, no urllib, por bloqueo de Cloudflare). |
| `zero/voice.py` | Voz vía **ElevenLabs**. `speak()` (mp3, voz clonada) y `speak_with_typing()` (wav, antepone un clip corto de teclado sintético — realismo puntual antes de una respuesta que "busca datos", no en cada turno). Ver [[docs/voice.md]]. |
| `zero/metaads.py` | **Meta Ads** por cliente (mock + Graph API real). CPL objetivo Chile, default Santiago (RM). |
| `zero/whatsapp_inbound.py` | Parseo de mensajes entrantes de WhatsApp (webhook). |
| `zero/memory.py` · `zero/memory_supabase.py` | Estado de sesión + secuencias de follow-up (archivo local o Supabase). |
| `zero/crm.py` · `zero/crm_supabase.py` | CRM durable (archivos `crm.json` o Postgres/Supabase). |
| `zero/store.py` | `make_crm()` / `make_memory()` — eligen Supabase si está configurado, si no local. |
| `zero/_supabase.py` | Helper HTTP compartido para PostgREST. |
| `zero/cloud_env.py` | **Config persistente en la nube**: guarda los secretos del dashboard en Supabase y los carga al arrancar (sobreviven a redeploys). |
| `zero/auth.py` | Login único de agencia: contraseña + tokens HMAC stateless. |
| `zero/_env.py` | Carga/escritura de `.env`. |
| `zero/sales.py` | Lógica de venta / pitch (apoya a PITCHWRITER). |
| `zero/board.py` · `zero/export.py` | Presentación: Kanban y CSV. Solo dibujan/exportan. |
| `api.py` | Backend web **FastAPI** del dashboard (endpoints de CRM, config, agentes, campañas, etc.). |
| `frontend/` | Dashboard **React/Vite** (tailwind, react-query, framer-motion). |
| `demo.py` | Recorrido animado del pipeline en terminal. |

## Selección de cerebro con fallback (`_agents_best` en `api.py`)

El dashboard elige: **Anthropic** (si hay `ANTHROPIC_API_KEY`) → **local** (si hay `LOCAL_MODEL`) → **mock**. Blindaje: ignora keys vacías, y si el modelo "live" **revienta o devuelve vacío**, reintenta en **mock** → el agente siempre responde. Ver [[03 - Backends]].

## Decisiones de diseño

- **Mock-first** — toda frontera con el mundo exterior tiene un mock fiel al contrato; lo real se enchufa después.
- **Política separada del mecanismo** — las reglas de negocio viven en `zero/config.py`; la lógica solo las aplica. Ver [[05 - Modelo de Negocio]].
- **Presentación separada de los datos** — `board.py` / `export.py` / `frontend/` solo muestran; no deciden.
- **Disciplina de alcance** — cada feature es un pasivo; adueñarse del núcleo antes de expandir. Equipo de 1.
- **Costo cero** — posponer toda integración de pago; perfeccionar lo gratis primero. Ver [[06 - Roadmap]].
- **Hosting local** (2026-06-10) — corre en esta máquina (backend :8800 + dashboard :5173) por la fricción de Render free (disco efímero que borraba keys). El `.env` local persiste; Supabase mantiene los datos en la nube.
- **Todo arranca solo** (2026-08-21) — `zero-backend` y `zero-tunnel` son unidades de sistema (`deploy/install.sh`, con sudo); `zero-dashboard` es unidad **de usuario** (`deploy/install-dashboard.sh`, sin sudo) porque necesita el node de nvm del home. Lo que lo levanta en el boot es `loginctl enable-linger diego`. `./start.sh` ya no levanta nada: solo reporta estado.

## TODOs / discrepancias detectadas

> [!todo]
> El `README.md` documenta `webapp.py` (dashboard stdlib) y el layout viejo; el código actual usa **`api.py` (FastAPI) + `frontend/` (React/Vite)**. Convendría actualizar el README al stack actual.

> [!todo]
> `prompts/` incluye `concierge.md`, `mediabuyer.md`, `pitchwriter.md` y `system_zero.md` que no aparecen en el layout del README. `docs/` tiene material extra (`motor-real.md`, `oferta-whatsapp.md`, `pitch.md`, prompts de personas `cristobal`/`fernanda`, `voice.md`) que vale la pena revisar si se documenta a fondo.
