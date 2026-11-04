# Pedido 2026-11-04 · motor-whatsapp: los mensajes «en revisión» no tienen salida

Origen: chequeo de salud del 2026-11-04. Lo toma el terminal motor-whatsapp.

**El problema.** Un mensaje entrante pasa a `needs_review` (tabla `received` de
`whatsapp-web-events.sqlite3`) cuando el envío de la respuesta del agente no se confirmó
o cuando el proceso murió mientras estaba `processing` (`zero/whatsapp_web.py`, ~296-319).
Ese estado no tiene salida. Ningún código lo mueve a `archived`: las 26 filas archivadas
que existen se archivaron a mano. Por eso `scripts/revisar-salud.py` (~268-275) repitió
«WhatsApp: 5 mensajes requieren revisión» durante 35 días con 5 mensajes de prueba del
2026-09-30. El día que un lead real caiga ahí, el aviso será idéntico al ruido de siempre
y nadie lo va a ver.

**Hecho hoy, para no repetirlo.** Diego confirmó que esas 5 filas eran de prueba (contacto
«Mauu»). Se archivaron a mano y hay respaldo en `~/respaldos/`. La bandeja quedó con 0 en
revisión.

**Lo que se pide.**
1. Una forma explícita de resolver un mensaje en revisión: marcarlo `archived` con el
   motivo. Puede ser una función en `zero/whatsapp_web.py` más un endpoint en `api.py`, o
   un script en `scripts/`. Ese camino es el único que escribe `archived`.
2. Que el aviso distinga lo nuevo de lo viejo: `revisar-salud.py` reporta cuántos hay y la
   antigüedad del más reciente («1 nuevo hace 20 min» no es lo mismo que «5 de hace 35
   días»), y un mensaje que entra a revisión se avisa una sola vez.
3. Tests en `tests/` para los dos puntos. La suite completa debe quedar en verde.

**Contexto que no está en el repo.** Hoy casi todos los contactos son pruebas de Diego
para entrenar al agente. La única clienta real es Marcia. Los leads reales llegarán cuando
se paguen los anuncios. Nunca enviar nada a un contacto sin leer antes el chat real y sin
la confirmación de Diego.

**No tocar.** El contenido de `prompts/*.md`, `frontend/`, y los datos `state.json` y
`crm.json`.
