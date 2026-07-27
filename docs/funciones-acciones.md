# Funciones que actúan — contrato de acciones

Una función programada ya no solo calcula: puede **pedir acciones** (mandar un
WhatsApp, mover un lead de etapa, dejar una nota) y ZERO las ejecuta.

## Cómo se pide una acción

Deja las acciones en `result`, como datos:

```python
# ctx trae {"leads": [...], "client_id": "...", "event": "manual"|"schedule.tick"}
sin_responder = [l for l in ctx["leads"] if l["stage"] == "contacted"]

result = {
    "actions": [
        {"type": "whatsapp", "lead": l["phone"], "body": f"Hola {l['name']}, ¿alcanzaste a ver lo que te mandé?"}
        for l in sin_responder
    ]
}
```

El `lead` de cada acción es el **email o teléfono** del destinatario (los campos
que ya vienen en `ctx["leads"]`).

## Los 4 tipos

| type | Qué hace | Campos |
|---|---|---|
| `whatsapp` | Manda un WhatsApp al lead | `lead`, `body` |
| `email` | Manda un correo al lead | `lead`, `body`, `subject` (opcional) |
| `stage` | Mueve el lead de etapa en el CRM | `lead`, `stage` |
| `note` | Deja una nota en el historial del lead | `lead`, `text` |

Una función que solo calcula sigue funcionando igual que siempre — si `result`
no es un dict con `actions`, no pasa nada raro, es un resultado normal.

## Por qué funciona así (y no mandando el mensaje directo)

El código de una función corre **aislado en Docker, sin red y sin
credenciales** (`--network=none`). Si para mandar un WhatsApp le diéramos red y
el token de Twilio, cualquier código pegado en el panel podría robarse las keys
o el CRM completo.

Por eso la función **nunca actúa**: solo *devuelve* lo que quiere que pase, como
datos. El lado confiable —fuera de Docker— valida cada acción y recién ahí la
ejecuta con el mismo Outbox/CRM de siempre. El sandbox no gana ni una capacidad
nueva.

## Los rieles (siempre activos)

1. **Tope de acciones por corrida** (`FUNCTION_MAX_ACTIONS_PER_RUN`, 25 por
   defecto): una función con un bug no puede convertirse en un envío masivo
   accidental. Lo que pasa del tope se rechaza y queda visible en el reporte.
2. **Solo los tipos permitidos** (`FUNCTION_ALLOWED_ACTION_TYPES` en
   `zero/config.py`) — sacar uno de esa lista lo deshabilita para todas las
   funciones, sin tocar código.
3. **Aislamiento entre clientes**: una función del cliente A no puede tocar
   leads del cliente B, aunque ponga su email exacto.
4. **Opt-out respetado**: un lead que pidió no ser contactado nunca recibe
   mensajes. (Mover de etapa o dejar una nota sí se permite: es registro
   interno, no contacto.)
5. **Envío real solo con `OUTBOX_LIVE=1`**: igual que cualquier otro envío del
   sistema. Sin esa variable, las acciones se registran pero no se manda nada
   de verdad — se puede probar sin riesgo.
6. **Si el código revienta, no se actúa**: las acciones de una corrida con
   error se descartan enteras.

Una acción inválida nunca frena a las demás ni tumba la corrida: se rechaza con
su motivo y queda en el reporte.

## Qué se ve después de correr

`last_run` incluye ahora un resumen de las acciones:

```json
{
  "at": "2026-07-23T12:00:00+00:00",
  "ok": true,
  "result_summary": "3 acciones aplicadas, 1 rechazada · {...}",
  "error": null,
  "actions": {"applied": 3, "rejected": 1}
}
```

Y la respuesta de `POST /api/functions/{id}/run` trae el detalle completo en
`run.actions`:

```json
{
  "requested": 4,
  "applied": 3,
  "results":  [{"type": "whatsapp", "lead": "...", "detail": "sent/twilio"}],
  "rejected": [{"action": {...}, "reason": "ese lead pidió no ser contactado (opt-out)"}]
}
```
