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

### Importar catálogo o preguntas frecuentes desde el dashboard

Contrato de CORE para DASHBOARD, verificación local del 2026-11-22. Se importa un
archivo por tipo (`kind` vale `catalogo` o `faq`). La carga admite CSV y la primera
hoja de XLSX, hasta 2 MiB y 2000 filas de datos.

1. `GET /api/onboarding/template?kind=catalogo` descarga el CSV con los encabezados.
   El catálogo requiere `nombre` y `precio` en pesos chilenos enteros. También acepta
   `sku`, `categoria`, `unidad`, `descripcion` y `stock`. La plantilla `faq` requiere
   `pregunta` y `respuesta`.
2. `POST /api/onboarding/preview?client=<id>` recibe JSON con `kind`, `filename` y
   `content_base64`. Devuelve `client`, `kind`, las filas válidas en `rows`, los
   errores por `fila`, `columna` y `motivo`, el `summary` y un `token`. Habilitar
   **Aplicar** solo cuando exista un token. Vale `null` si hay errores o faltan filas
   válidas. La vista previa conserva la ficha y los precios vigentes.
3. `POST /api/onboarding/apply?client=<id>` recibe `{"token":"…","motivo":"…"}`
   (`motivo` opcional). Devuelve `client`, `kind`, `version`, `chars`, `aplicadas`
   y `pricing_items` (número de productos o `null` para FAQ). Regenera la sección
   correspondiente de la ficha y conserva el texto manual. El catálogo reemplaza
   además la lista completa de precios del cotizador. El rollback de la ficha
   restaura su texto. Para recuperar los precios anteriores hay que volver a
   importar ese catálogo.
4. `GET /api/onboarding/status?client=<id>` devuelve `client`, `listo` e `items`.
   Cada ítem trae `clave`, `ok`, `detalle`, `accion` y `obligatorio`. Para que
   `listo` sea verdadero se requieren ficha manual, catálogo, FAQ y credenciales
   de WhatsApp configuradas. Los huecos abiertos se muestran para seguimiento.

**Resumen de la vista previa.** Mostrar `validas`, `con_error`, `nuevas`,
`cambian`, `sin_cambio` y `se_eliminan`. Esta última cifra cuenta las entradas
vigentes ausentes del archivo y permite avisar antes de reemplazarlas. En catálogo,
la comparación con el cotizador usa el identificador del producto, nombre, precio
y unidad. Un cambio limitado a categoría, descripción o stock puede aparecer como
`sin_cambio` y aun así actualizar el texto de la ficha.

**Errores y reintentos.** Un 413 indica exceso de tamaño o filas, un 415 indica
formato XLS antiguo y un 422 indica archivo ilegible. Si la ficha tiene marcadores
dañados, preview y apply devuelven 409. PoolEdge (`losetaschile`) admite vista
previa y devuelve 409 al aplicar. Cada token pertenece a un cliente, dura
30 minutos y sirve para una aplicación. Se conservan hasta 8 por cliente y 200
por proceso. Ante 404 por token ausente o 410 por expiración, volver a crear la
vista previa. Apply y status también devuelven 404 para un cliente desconocido.

### ICP (perfil del cliente ideal — ya existía el GET, ahora también se guarda)

- `GET /api/icp?client=<id>` → `{"client", "icp": {...}}`
- `POST /api/icp?client=<id>` — body `{"icp": {...}}`

### Lista de precios + presupuestos (2026-07-02)

La aritmética del presupuesto es **determinista** (código, `zero/quotes.py`); el LLM
nunca calcula. El trabajador carga la lista de precios y el agente cotiza solo.

- `GET /api/pricing?client=<id>` → `{"client", "pricing": Pricing}`
  `Pricing = {"currency": "CLP", "iva_rate": 0.19, "items": [{"id", "name",
  "unit_price", "unit"|null}]}`
- `POST /api/pricing?client=<id>` — body `{"pricing": Pricing}`. Se normaliza al
  entrar: ítems sin `name` o sin `unit_price > 0` se descartan; `id` se deriva del
  nombre si falta. Devuelve el pricing ya normalizado (mostrar ese).
- `POST /api/quote` — cotizador directo (sin chat). Body:
  `{"client": "acme", "items": [{"id": "sitio-web", "qty": 2}]}`
  → `{"client", "quote": Quote, "text": str}` · 404 si ningún ítem existe.
  `Quote = {"currency", "lines": [{"id", "name", "qty", "unit_price", "subtotal"}],
  "subtotal", "iva_rate", "iva", "total", "unmatched": [ids]}`

### Chat de prueba (sin WhatsApp, no envía nada, no persiste)

- `POST /api/whatsapp/simulate` — body:
  ```json
  {"client": "acme", "message": "texto del lead",
   "history": [{"role": "lead"|"agent", "text": "..."}],   // opcional
   "vendor_id": "stefano"}                                   // opcional
  ```
  → `{"reply": str, "mode": "live"|"mock", "quote": Quote|null}`
  **El frontend mantiene la transcripción** y la manda completa en `history` en cada
  turno (el server no guarda ensayos). `vendor_id` permite probar una personalidad
  sin asignarla. `mode: "mock"` = no hay modelo configurado (mostrar aviso).
  `quote` viene cuando el lead pidió precios de ítems del catálogo: el `reply` ya
  incluye el bloque de presupuesto como texto; `quote` trae los números por si la
  UI quiere pintar una tarjeta bonita.

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
