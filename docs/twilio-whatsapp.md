# WhatsApp vía Twilio (plan B)

Twilio es el **segundo proveedor** del canal WhatsApp — mismo contrato, mismo
CONCIERGE, mismo CRM; solo cambia el transporte. El plan A sigue siendo Meta
Cloud API directo (WABA en revisión); esto existe para no quedar bloqueado
mientras tanto. Decidido el 2026-07-21 (comparación Twilio vs 360dialog en
`docs/roadmap.md`, sección "Plan B WhatsApp vía BSP").

**Importante:** Twilio NO salta la aprobación de Meta para producción — el WABA
se crea igual, vía el onboarding de Twilio. Lo que sí da **al tiro** es el
**sandbox**: probar envío y recepción reales con tu propio teléfono, hoy, sin
esperar a nadie.

## 1. Crear la cuenta y el sandbox (consola, ~10 min)

1. Crea la cuenta en <https://www.twilio.com/try-twilio> (el trial no pide tarjeta).
2. En la consola, ve a **Messaging → Try it out → Send a WhatsApp message**.
   Ahí está el **sandbox**: un número compartido de Twilio (ej. `+1 415 523 8886`)
   y un **join code** (ej. `join violet-cat`).
3. Desde tu WhatsApp personal, manda `join <code>` a ese número. Con eso tu
   teléfono queda "dentro" del sandbox y puede conversar libremente (el opt-in
   reemplaza a las plantillas mientras estés en sandbox).

## 2. Las 3 keys

| Key | Dónde sale |
|---|---|
| `TWILIO_ACCOUNT_SID` | Consola → home → **Account Info** → Account SID (empieza con `AC`) |
| `TWILIO_AUTH_TOKEN` | Mismo panel → Auth Token (botón "show") |
| `TWILIO_WHATSAPP_FROM` | El número del sandbox, ej. `+14155238886` (después, tu número real) |

Pégalas en **Configuración** del dashboard (card Twilio) — o a mano en `.env`.
Nada se envía de verdad todavía: sin `OUTBOX_LIVE=1` todo sigue en mock.

## 3. Activar Twilio como proveedor

En Configuración (o `.env`):

```
WHATSAPP_PROVIDER=twilio    # default: meta — borrar/poner "meta" para volver al plan A
OUTBOX_LIVE=1               # el mismo interruptor de siempre para envío real
```

Sin `WHATSAPP_PROVIDER`, todo se comporta exactamente igual que hoy (Meta).

## 4. Recibir mensajes (webhook)

En la página del sandbox, campo **"When a message comes in"**, pega:

```
https://<tu-host-público>/api/webhooks/twilio-whatsapp     (método: POST)
```

- La API corre local (servicio `zero-backend`, :8800), así que necesitas una URL
  pública hacia ese puerto. Ya hay una: el servicio `zero-tunnel` levanta ngrok
  con dominio fijo y arranca solo con el sistema.
- Si hay túnel/proxy delante, agrega en `.env` la URL exacta que pegaste en la
  consola: `TWILIO_WEBHOOK_URL=https://<tu-host-público>/api/webhooks/twilio-whatsapp`.
  La firma de Twilio se calcula sobre esa URL carácter por carácter; detrás de un
  proxy el server ve otra URL y sin esta variable rechazaría todo con 403.
- Requests sin la firma `X-Twilio-Signature` válida se rechazan con 403 sin
  procesar nada — mismo criterio que el webhook de Meta.

## 5. Probar con tu teléfono

1. `join <code>` ya enviado (paso 1).
2. Escribe cualquier cosa al número del sandbox — debería contestarte el
   CONCIERGE (si el remitente matchea un lead del CRM; si no, queda registrado
   como `inbound_unmatched` en la memoria).
3. Envío saliente: corre un pipeline o responde desde el dashboard; con
   `OUTBOX_LIVE=1` + provider twilio, el mensaje sale por Twilio a tu WhatsApp.

## Producción (cuando toque)

- El WABA y el número propio se crean vía el onboarding de WhatsApp en la
  consola de Twilio (pasa por aprobación de Meta igual que el plan A).
- Contacto en frío (fuera de la ventana de 24 h) exige plantilla pre-aprobada
  también en Twilio: se crea en **Content Template Builder**, Meta la aprueba, y
  su SID (empieza con `HX`) va en `.env` como `TWILIO_CONTENT_SID`. Sin eso, un
  envío tipo template devuelve un error claro ("template no configurado en
  Twilio") — nunca manda otra cosa en silencio.
- From por vendedor (cuando haya más de un número): `TWILIO_WHATSAPP_FROM_<ID>`
  (ej. `TWILIO_WHATSAPP_FROM_FERNANDA`), con fallback al global — espejo del
  patrón `WHATSAPP_TOKEN_<ID>` de Meta.
- Costo: USD $0.005 por mensaje (entrante y saliente) + la tarifa de
  conversación de Meta. El sandbox es gratis.
