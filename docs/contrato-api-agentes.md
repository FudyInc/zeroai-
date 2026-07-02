# Contrato API — sección "Agentes WhatsApp" del dashboard

Para la terminal 🎨 DESIGN. Backend listo y verificado (2026-07-02, terminal WORKER).
Base: la API FastAPI de `api.py` (dev: `uvicorn api:app --port 8800`). Todos los
endpoints van bajo `/api` y usan el mismo auth por token Bearer que el resto (si
`AUTH_PASSWORD` está seteado; en dev abierto).

## La idea de la sección (para quien la diseña)

Un trabajador **que no sabe de IA** debe poder, en 3 pasos simples:
1. Pegar la **ficha de la empresa** cliente (texto libre: qué vende, precios, horarios,
   políticas) en un textarea grande.
2. Elegir una **personalidad** (Fernanda, Stéfano, …) de un catálogo con foto/tono.
3. Apretar **"Desplegar agente"** → esa personalidad atiende a los leads de esa empresa
   con ese conocimiento.
Extra: un **chat de prueba** para conversar con el agente antes de que hable con leads
reales, y el **hilo de conversación** de cada lead para supervisión.

## Endpoints

### Personalidades (catálogo)

- `GET /api/vendors` → `{"vendors": [Vendor], "default": "fernanda"}`
  `Vendor = {"id", "name", "tone", "photo", "phone", "whatsapp_phone_id"}`
- `POST /api/vendors` — crear/editar. Body: `{"id"?, "name", "tone"?, "photo"?,
  "phone"?, "whatsapp_phone_id"?}`. Sin `id`, se deriva del nombre. Solo pisa los
  campos enviados. → `{"vendor": Vendor}`

### Asignación ("deploy")

- `GET /api/vendor?client=<id>` → `{"client", "vendor": Vendor}` (el asignado o el default)
- `POST /api/vendor?client=<id>` — body `{"vendor_id": "fernanda"}` → 404 si no existe.

### Base de conocimiento (la ficha de la empresa)

- `GET /api/knowledge?client=<id>` → `{"client", "knowledge": str}`
- `POST /api/knowledge?client=<id>` — body `{"knowledge": str}` (texto libre, se
  guarda tal cual; el motor usa los primeros ~4000 chars) → `{"saved": true, "chars": n}`

### ICP (perfil del cliente ideal — ya existía el GET, ahora también se guarda)

- `GET /api/icp?client=<id>` → `{"client", "icp": {...}}`
- `POST /api/icp?client=<id>` — body `{"icp": {...}}`

### Chat de prueba (sin WhatsApp, no envía nada, no persiste)

- `POST /api/whatsapp/simulate` — body:
  ```json
  {"client": "acme", "message": "texto del lead",
   "history": [{"role": "lead"|"agent", "text": "..."}],   // opcional
   "vendor_id": "stefano"}                                   // opcional
  ```
  → `{"reply": str, "mode": "live"|"mock"}`
  **El frontend mantiene la transcripción** y la manda completa en `history` en cada
  turno (el server no guarda ensayos). `vendor_id` permite probar una personalidad
  sin asignarla. `mode: "mock"` = no hay modelo configurado (mostrar aviso).

### Hilo real de un lead (supervisión)

- `GET /api/conversation?client=<id>&lead=<lead_key>&limit=50`
  → `{"client", "lead", "turns": [{"role": "lead"|"agent", "text", "at": iso}]}`
  El `lead_key` es el `key` que ya viene en los records del CRM (`/api/leads/...`).
  Estos turnos los registra el motor solo (mensajes entrantes reales + respuestas del
  agente); el dashboard solo los muestra.

### Estado de configuración (ya existía, campos nuevos)

- `GET /api/config` ahora incluye `"local_model"` (str|null) y `"discover"`
  ("web"|"none") para mostrar el estado del cerebro.

## Notas

- Todo persiste en el estado de sesión (archivo local o Supabase si está configurado —
  mismo snapshot, sin cambios para el frontend).
- El envío real de WhatsApp aún no está (falta credencial de Meta); el "deploy" hoy
  activa la personalidad para el chat de prueba, el email real y el webhook cuando exista.
