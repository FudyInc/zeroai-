# GO-LIVE — interruptores para pasar ZERO de mock a real

Esta rama (`integration`) corre **mock-first**: todo funciona offline, sin keys y sin
gasto. Los mocks **se quedan** (son la red de seguridad y el modo de desarrollo). Para
encender el modo real, activa estos interruptores **en orden**. Cada uno es independiente:
puedes encender solo el motor sin enviar, o solo email, etc.

> Regla de oro: **ningún secreto va a archivos versionados.** Todo lo de abajo son
> variables de entorno (`.env` local, gitignored) o flags de ejecución.

---

## (a) Motor real — el LLM responde de verdad

Por defecto los agentes corren en **mock** (respuestas deterministas, sin red). Para que
piensen de verdad hay dos backends:

- **Nube (Anthropic):** define `ANTHROPIC_API_KEY` y corre con `--live`.
  - CONCIERGE (la conversación con el lead) está mapeado a **`claude-opus-4-8`** —
    es la cara del cliente, vale el modelo fuerte.
  - Los sub-agentes de pipeline (PROSPECTOR, QUALIFIER, OUTREACH, TRACKER, ANALYST)
    usan **`claude-sonnet-4-6`** (más barato). El orquestador ZERO usa `claude-fable-5`.
  - Se paga por token, no por tiempo. Sin tráfico, $0.
- **Local (gratis):** modelo OpenAI-compatible (Ollama/vLLM) con `--local`
  `--local-model "<modelo>"` `--local-url "http://<host>:11434/v1"`. Cero costo.
  Ideal para el pipeline por lotes; corre en un PC con GPU/CPU dedicado, **nunca**
  en un equipo que no aguante la carga.

```bash
# Nube
export ANTHROPIC_API_KEY=sk-ant-...
python3 main.py --client acme --tier GROWTH --query "fintech LATAM" --live

# Local
python3 main.py --client acme --tier GROWTH --query "fintech LATAM" \
  --local --local-model "qwen2.5:7b-instruct-q4_K_M" --local-url "http://IP:11434/v1"
```

La política de qué modelo usa cada agente vive en `zero/config.py` (constantes `FABLE`,
`OPUS`, `SONNET`) y en el atributo `model` de cada agente.

## (b) Envío real — los mensajes salen de verdad

Incluso con credenciales presentes, el outbox es **mock por defecto**. Para enviar de
verdad:

```bash
export OUTBOX_LIVE=1
```

- **Email (SMTP):** define `SMTP_HOST` (+ usuario/clave/puerto según tu proveedor).
- Sin `OUTBOX_LIVE=1`, todo queda registrado en el CRM como envío *mock* (no sale nada).

## (c) WhatsApp por vendedor — credenciales + webhook

Cada vendedor (Fernanda, Stéfano, ...) envía desde **su propio número** de WhatsApp
Business. Las credenciales se resuelven en `zero/vendors.py::credentials_for`:

- `phone_id`: el `whatsapp_phone_id` del vendedor (en su record del catálogo), o el global
  `WHATSAPP_PHONE_ID` como fallback.
- `token`: `WHATSAPP_TOKEN_<ID_EN_MAYÚSCULAS>` (ej. `WHATSAPP_TOKEN_STEFANO`), o el global
  `WHATSAPP_TOKEN` como fallback. **El token nunca va en el record ni en ningún JSON.**

```bash
export WHATSAPP_TOKEN=...            # token global (fallback)
export WHATSAPP_PHONE_ID=...         # phone_id global (fallback)
export WHATSAPP_TOKEN_FERNANDA=...   # token propio de Fernanda
export WHATSAPP_TOKEN_STEFANO=...    # token propio de Stéfano
export WHATSAPP_VERIFY_TOKEN=...     # para el handshake del webhook de Meta
export WHATSAPP_APP_SECRET=...       # para verificar la firma de cada mensaje entrante
```

**Entrante (dos vías):** el webhook `GET/POST /api/webhooks/whatsapp` recibe los mensajes;
ZERO rutea la respuesta al vendedor dueño del número que recibió el mensaje
(`to_phone_id` → `vendor_by_phone_id`). Para que Meta llame al webhook necesitas una
**URL pública** apuntando al backend:

- Verifica el vínculo de cada número con `GET /api/whatsapp/status` (pega contra la Graph
  API real; error limpio si falta credencial).
- Expón el backend con un dominio público o un túnel (ngrok/deploy) y registra esa URL +
  el `WHATSAPP_VERIFY_TOKEN` en el panel de Meta.

**Seguridad del webhook (obligatorio antes de exponerlo en público):** sin
`WHATSAPP_APP_SECRET`, `POST /api/webhooks/whatsapp` **rechaza todo** con `403` — a
propósito, para que nadie pueda mandar mensajes falsos haciéndose pasar por un lead.
El valor es el **App Secret** de tu app de Meta (Configuración de la app → Básica —
distinto del token que usas para *enviar* mensajes). Sin este secreto configurado,
el webhook simplemente no recibe nada — no hay forma de activarlo "a medias".

**Plantilla para contacto en frío (obligatorio antes de mandar el primer toque real):**
Meta exige una plantilla pre-aprobada para el primer mensaje a un lead que nunca
escribió, o cualquier mensaje fuera de la ventana de 24h desde su último mensaje —
un mensaje de texto libre ahí es **rechazado** por la Graph API real. Sin esto
configurado, ZeroAI no manda nada en frío (queda como error visible en el CRM, nunca
intenta un texto libre que Meta rechazaría).

1. En **Meta Business Manager → WhatsApp Manager → Plantillas de mensajes**, crea una
   plantilla (categoría "Utility" suele aprobarse más rápido que "Marketing") con un
   placeholder de cuerpo, ej.: *"Hola {{1}}, te contacto porque..."*. Espera la
   aprobación de Meta (puede tardar de horas a un par de días).
2. Una vez aprobada, anota su nombre exacto y el código de idioma en
   `zero/config.py::WHATSAPP_TEMPLATE`:
   ```python
   WHATSAPP_TEMPLATE = {"name": "nombre_exacto_de_la_plantilla", "language": "es"}
   ```
3. Esto **no afecta** las respuestas a un lead que ya escribió (`handle_inbound`) —
   esas siguen como texto libre, están dentro de la ventana de 24h.
4. Costo: Meta cobra por conversación una vez que empiezas a mandar plantillas con un
   número real (no es gratis como el resto de ZeroAI) — revisa el precio vigente para
   tu país en el panel de WhatsApp Business antes de activar `OUTBOX_LIVE=1`.

---

## Checklist de encendido

- [ ] (a) `ANTHROPIC_API_KEY` + `--live` (o `--local` para gratis) — el motor responde real.
- [ ] (b) `OUTBOX_LIVE=1` (+ `SMTP_HOST` para email) — los mensajes salen.
- [ ] (c) `WHATSAPP_TOKEN[_<VENDEDOR>]` + `WHATSAPP_PHONE_ID` + `WHATSAPP_VERIFY_TOKEN`
      y URL pública del webhook — WhatsApp de dos vías por vendedor.
- [ ] (c.1) Plantilla aprobada por Meta + `WHATSAPP_TEMPLATE` en `zero/config.py` —
      sin esto, el primer contacto y los follow-ups por WhatsApp NO se mandan (quedan
      como error en el CRM, a propósito, en vez de un texto libre que Meta rechazaría).
- [ ] (c.2) `WHATSAPP_APP_SECRET` — sin esto, el webhook rechaza TODO con 403 a
      propósito (no hay forma de recibir mensajes reales sin este secreto).

Hasta encender (a)/(b)/(c), todo sigue corriendo en mock: seguro para desarrollar y para
probar la suite (`python3 -m unittest discover -s tests -t .`).
