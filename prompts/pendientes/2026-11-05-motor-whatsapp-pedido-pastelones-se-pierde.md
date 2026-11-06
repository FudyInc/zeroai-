# Pedido 2026-11-05 · motor-whatsapp: el pedido de pastelones no le llega claro a nadie

Origen: conversación real de Maureen (+56972828756), 2026-11-05 22:03–22:07. Se trata
como clienta real. Lo toma el terminal motor-whatsapp.

**Lo que pasó.** El agente tomó el pedido completo: pastelones, 40 m², Gregoriano,
amarillo y despacho con ubicación. Después le dijo «El equipo arma el presupuesto y te
escribe por este chat» (`zero/orchestrator.py` ~1405-1412). Pero:

1. **No se armó presupuesto ni llegó nada al grupo.** El camino de pastelones solo deja
   un `attention` («Pastelones: confirmar el tamaño del modelo y cotizar»), que va a
   `knowledge_gaps` (~2191-2196). No hay `internal_budget_signatures` para ella y el grupo
   PRESUPUESTOS no recibió nada.
2. **El aviso que sí quedó engaña.** Maureen mandó la ubicación dos veces. La segunda vez
   el agente respondió «Necesito revisar tu consulta…», y su único ítem en
   `knowledge_gaps` quedó como `tipo: pregunta`, «El agente repitió una respuesta», con
   la ubicación como pregunta. El «cotizar pastelones» no aparece. Hay que verificar si la
   segunda entrada pisó a la primera.
3. **Se ofreció un modelo sin precio.** El menú incluye «Gregoriano»
   (`zero/losetas_polls.py:41`), pero no está en `pricing` ni en la ficha. El agente no
   puede ofrecer un producto que la lista no respalda.
4. **No retomó la conversación.** A «¿cómo me llamo?» respondió «Buenas noches Maureen.
   ¿En qué te puedo ayudar hoy?», como si empezara de cero, con un presupuesto pendiente.
   Regla de Diego: cada cliente tiene una sola conversación y el agente siempre la retoma
   (ver `2026-11-05-motor-whatsapp-recordatorio-presupuesto.md`).

**Lo que se pide.**
1. Un pedido de pastelones completo llega al grupo de revisión con un borrador, igual
   que los bordes: contacto, modelo, color, m², entrega y ubicación. Si falta precio,
   el borrador lo dice («precio pendiente») en vez de no enviarse.
2. Un mensaje repetido (misma ubicación, mismo texto) no degrada ni reemplaza un aviso de
   pedido. El cliente recibe un acuse normal, no «necesito revisar tu consulta».
3. Los modelos del menú salen de `pricing`/ficha, no de una lista fija en el código. O
   bien, si se mantiene la lista, un test falla cuando un modelo ofrecido no tiene
   respaldo.
4. Con un presupuesto en curso, cualquier mensaje del cliente se responde desde ese
   estado (p. ej. «Tu presupuesto de 40 m² de Gregoriano amarillo con despacho está en
   revisión»).
5. Tests en `tests/` para los cuatro puntos, con esta conversación anonimizada como caso.
   La suite completa debe quedar en verde.

**No tocar.** El contenido de `prompts/*.md`, `frontend/`, y los datos `state.json` y
`crm.json`. No escribirle a Maureen: su presupuesto lo manda el equipo.
