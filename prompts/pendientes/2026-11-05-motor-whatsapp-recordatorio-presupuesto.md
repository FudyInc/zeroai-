# Pedido 2026-11-05 · motor-whatsapp: recordar el presupuesto que el cliente no contestó

Origen: conversación con Diego del 2026-11-05. Lo toma el terminal motor-whatsapp.

**El problema.** Cuando un cliente de losetaschile recibe un presupuesto y no responde,
nada vuelve a la conversación. Con Marcia, la única clienta real, quedamos en preguntarle si
quería retomar su cotización y nadie lo hizo. Diego lo llama «conciencia de seguimiento»: el
agente tiene que saber qué conversaciones quedaron pendientes.

La cadencia que ya existe (`FOLLOWUP_STEPS` en `zero/config.py`, días 3/7/14) no sirve tal
cual. Es la de prospección B2B saliente y cuenta desde el primer contacto del negocio, no
desde un presupuesto de WhatsApp.

**Decisiones ya tomadas por Diego.**
- Un recordatorio a las **24 horas** del presupuesto y otro a los **5 días**. Después se
  cierra la secuencia.
- **Nada sale directo al cliente.** Cada recordatorio llega primero al grupo de revisión
  de losetaschile (`LOSETASCHILE_REVIEW_GROUP_ID`), con el texto propuesto y el contacto, y
  solo se envía cuando una persona lo aprueba ahí. Es el mismo camino que siguen hoy los
  presupuestos (`zero/losetas_review.py`).
- Es una regla del producto: corre con un timer de systemd, como `zero-instagram.timer`.
  No es un `/loop` ni nada que dependa de una sesión abierta.

**Lo que se pide.**
1. Plazos (24 h, 5 días), horario hábil y número máximo de recordatorios en `zero/config.py`.
2. Un recordatorio se propone solo si se cumplen las tres condiciones:
   - el cliente no escribió después del presupuesto;
   - el chat no tiene traspaso a humano activo;
   - estamos en horario hábil (`WHATSAPP_TIME_ZONE`).
   Si el cliente responde o el chat pasa a humano, la secuencia se cancela.
3. La aprobación en el grupo usa un gesto mínimo (p. ej. responder citando con «ok»), y
   queda registrado quién aprobó y cuándo. Si nadie aprueba, el recordatorio no se envía
   y no se acumula: el de 5 días reemplaza al de 24 h pendiente.
4. El texto que efectivamente se envía queda en el historial del agente. Si el cliente
   contesta, el agente tiene que saber que la conversación la retomamos nosotros.
5. Tests en `tests/` para todos estos casos:
   - el cliente no contestó, así que se propone;
   - el cliente contestó, así que no se propone;
   - el chat tiene traspaso activo;
   - es fuera de horario;
   - el recordatorio no fue aprobado;
   - la secuencia se cierra después del segundo recordatorio.
   La suite completa debe quedar en verde.

**Riesgo de diseño que hay que resolver primero.** Hoy el presupuesto final se arma en el
grupo y una persona se lo manda al cliente **desde el teléfono**. La memoria del agente no
ve esos envíos manuales, y tras un reinicio el caché del puente (`/chats/{id}/messages`)
viene casi vacío: el 2026-11-05 el chat de Marcia solo mostraba un mensaje. Antes de
programar hay que definir de dónde sale, de forma confiable, «cuándo se mandó el
presupuesto» y «si el cliente contestó después». Si no hay una fuente confiable, la regla
no puede decidir sola. Hay que reportarlo en vez de adivinar.

**Contexto que no está en el repo.** Casi todos los contactos son pruebas de Diego. La
única clienta real es Marcia. Nunca enviar nada a un contacto sin leer antes el chat real y
sin la confirmación de Diego. La aprobación en el grupo cumple esa regla para estos
recordatorios.

**No tocar.** El contenido de `prompts/*.md`, `frontend/`, y los datos `state.json` y
`crm.json`.
