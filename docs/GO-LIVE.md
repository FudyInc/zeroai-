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
```

**Entrante (dos vías):** el webhook `GET/POST /api/webhooks/whatsapp` recibe los mensajes;
ZERO rutea la respuesta al vendedor dueño del número que recibió el mensaje
(`to_phone_id` → `vendor_by_phone_id`). Para que Meta llame al webhook necesitas una
**URL pública** apuntando al backend:

- Verifica el vínculo de cada número con `GET /api/whatsapp/status` (pega contra la Graph
  API real; error limpio si falta credencial).
- Expón el backend con un dominio público o un túnel (ngrok/deploy) y registra esa URL +
  el `WHATSAPP_VERIFY_TOKEN` en el panel de Meta.

---

## Checklist de encendido

- [ ] (a) `ANTHROPIC_API_KEY` + `--live` (o `--local` para gratis) — el motor responde real.
- [ ] (b) `OUTBOX_LIVE=1` (+ `SMTP_HOST` para email) — los mensajes salen.
- [ ] (c) `WHATSAPP_TOKEN[_<VENDEDOR>]` + `WHATSAPP_PHONE_ID` + `WHATSAPP_VERIFY_TOKEN`
      y URL pública del webhook — WhatsApp de dos vías por vendedor.

Hasta encender (a)/(b)/(c), todo sigue corriendo en mock: seguro para desarrollar y para
probar la suite (`python3 -m unittest discover -s tests -t .`).
