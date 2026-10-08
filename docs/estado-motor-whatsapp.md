# Motor del agente de WhatsApp

**Código activo y pruebas locales:** 2026-10-07. El backend reinició con
`main` en `5566e10` y respondió a `/api/health`. GitHub recibió el código y
Vercel informó un despliegue de producción `Ready` el mismo día.
**Almacén de producción:** ficha ZeroAI y conexión Meta comprobadas.
**Conversación real:** Diego confirmó respuestas en el WhatsApp de LosetasChile
el 2026-10-06 23:41 Chile, antes de la corrección del cálculo de bordes.
El catálogo activo de LosetasChile ya incluye el esquinero; el subtotal de
productos de un pedido 6 × 3 m se calculó con historial y precios reales en una
simulación sin envío. El 2026-10-07 se observó un subtotal real por WhatsApp
tras «Okay el presupuesto»; lo calculó el código activo, no Qwen 3. Falta una
conversación real de ZeroAI por Meta.

**Flujo de LosetasChile activo en el backend local 2026-10-08:** la imagen
entregada por Diego muestra siete colores etiquetados. El agente puede enviarla
por WhatsApp Web, recoger el color elegido y preparar un presupuesto interno
con nombre de perfil opcional y número obligatorio. Ese presupuesto no se envía
automáticamente al cliente. Diego creó «Presuouesto losetas ia»; se verificó
como grupo separado de «Losetas Diego» en la cuenta Web asignada. Se configuró
como destino en el servicio local y se confirmó un mensaje técnico aceptado y
visible en el grupo, sin datos de clientes. Pasaron 1048 pruebas Python y la
revisión de sintaxis del puente. Falta comprobar el recorrido real de imagen,
elección de color y presupuesto con un mensaje nuevo desde el teléfono de Diego.
El cambio aún no se publicó en GitHub ni en Vercel.
Diego confirmó después que la prueba técnica llegó al grupo correcto.
En el primer intento del recorrido desde el cliente, el mensaje entrante
quedó registrado pero el chat ya tenía una pausa automática por una consulta
anterior no interpretable. No se envió respuesta. La pausa de ese chat de
prueba se liberó y se comprobó el estado nuevo el 2026-10-08; el mensaje
anterior no se reprocesó. Falta un mensaje nuevo con las medidas completas.

**Ajustes locales del 2026-10-08, pendientes de activar:** las consultas por
bordes de piscina sin largo y ancho preguntan primero por las medidas en
metros. La respuesta a esa pregunta continúa el flujo sin depender del modelo.
Diego prefirió Qwen 3 de 14B tras la prueba temporal y pidió dejarlo como
modelo habitual de WhatsApp. Se añadió una configuración específica del canal
para mantener el modelo de los otros agentes; la muestra previa fue pequeña y
Qwen 3 tardó más. Pasaron 1053 pruebas Python. Falta activar el servicio y
comprobar que el bot indique Qwen 3 como modelo real.

**Prueba temporal de Qwen 3 2026-10-07:** el backend WhatsApp usó Qwen 3 de
14B durante una prueba desde el teléfono de Diego. Se observó un saludo y una
respuesta de subtotal; el subtotal vino del cotizador activo y no mide la
calidad del modelo. Se restauró Qwen 2.5; `/api/health` y el puente Web
respondieron correctamente. El resto de agentes mantuvo su modelo.

**Evaluación de modelo local 2026-10-07:** el servicio sigue configurado con
`qwen2.5:14b-instruct-q4_K_M`. La máquina tiene una RTX 5060 Ti de 16 GB.
Se descargó `qwen3:14b` para una comparación local sin mensajes a clientes ni
cambio del backend. Con la ficha versionada de ZeroAI en memoria temporal,
ambos respondieron cuatro consultas comerciales sin cifras o garantías
inventadas. Qwen 2.5 tardó 2,3–9,6 s por consulta; Qwen 3 tardó 5,6–19,5 s
con razonamiento y 5,5–12 s sin él. La muestra es pequeña y no prueba una
mejora general. El modelo activo volvió a quedar cargado en GPU. Para evaluar
un modelo de mayor tamaño en esta máquina hace falta considerar más VRAM;
queda pendiente una comparación representativa antes de cambiar producción.

**Incidente 2026-10-07:** una conversación real de LosetasChile respondió
«alrededor de 18 pastelones» a «Necesito pastelones». Esa frase no pedía un
cálculo y llegó al LLM. Diego precisó que, con el pedido ya confirmado, el
motor debe guardar las cantidades y enviar el presupuesto con total, sin
explicar las piezas en una frase suelta. La corrección local usa el cotizador
estructurado y deriva cifras no respaldadas del modelo a revisión. Queda
pendiente su publicación y comprobación en una conversación nueva.

**Comprobación 2026-10-07:** el backend respondió a `/api/health` con el
subtotal de productos y la segunda corrección de bordes ya en `main`. Después
se integró `6147176`, que mejora el contexto y la revisión de consultas. La
revisión del cotizador encontró dos consultas de precios no cubiertas. Su
corrección quedó activa en el backend con `5566e10` y se publicó en `main`;
queda pendiente una prueba real de la respuesta.

El código integrado admite Meta Cloud y sesiones WhatsApp Web asignadas por
negocio. El envío real exige credenciales propias del negocio. ZeroAI ya tiene
sus claves Meta por negocio; LosetasChile conserva su sesión WhatsApp Web.

El webhook de Meta valida el mensaje, obtiene el ID del número receptor y, si Meta
lo entrega, el nombre del perfil del remitente. El ID receptor determina la empresa
antes de buscar al contacto en el CRM. Si dos empresas comparten receptor, el
motor responde solo si el remitente ya existe en una única empresa asociada.
Ante dos coincidencias o un remitente nuevo no elige una por su cuenta.
Con varias empresas, un receptor desconocido
tampoco se asigna a ZeroAI salvo que coincida con el receptor global configurado.
El número global de Meta busca primero un contacto existente entre las empresas
que usan ese número; si hay una sola coincidencia, usa su ficha. Si hay varias,
no responde. Para un contacto nuevo conserva el cliente predeterminado. Una
empresa con número propio no entra en la búsqueda del número global.
Un receptor asignado a un vendedor sin empresa asociada también queda sin respuesta.
Un nombre de perfil
completa un nombre vacío; nunca reemplaza uno ya guardado. Si no hay nombre, el
primer saludo usa «Estimado/a».

Los mensajes y respuestas enviadas quedan en la memoria por empresa y contacto.
CONCIERGE recupera turnos relevantes del historial completo y envía un contexto
compacto al modelo local. Una respuesta cuyo envío falló no se agrega como turno
del agente, y una oferta pendiente
no se marca cumplida si falló el envío. Con `OUTBOX_LIVE=1`, la falta de
credenciales Meta produce un error de envío, no un resultado simulado como enviado.

El 2026-10-07 se detectó que «Ya revisé tu consulta» escapaba al control de
afirmaciones de revisión. La corrección incorpora ese borrador real como
regresión, conserva modelo, medidas y ubicación en chats largos y permite un
saludo después de una revisión automática con aviso. Está desplegada en el
backend local: salud OK y puente WhatsApp Web en estado `ready`. La secuencia
se comprobó con pruebas controladas, sin enviar mensajes a clientes; queda
pendiente observar una conversación real posterior al despliegue.

PoolEdge aún no tiene conectado el cotizador de despacho. Por eso, una consulta de
precio recibe una solicitud de datos sin pasar por el modelo ni adjuntar un total.
La plantilla de `docs/plantilla-presupuesto-pooledge.md` sigue pendiente de integrar.
El cotizador directo `/api/quote` también rechaza el presupuesto de PoolEdge
hasta que exista la revisión del despacho.

La versión integrada está activa en el backend, pero la prueba de webhook vacío
no confirma entrega de una conversación real. La ficha activa de ZeroAI en
Supabase coincidió con la versionada (3982 caracteres); Graph API reconoció el
número Meta. PoolEdge no figura como cliente activo. No se mostraron secretos,
números ni datos de leads durante estas comprobaciones.

## Comprobación 2026-10-06

El servicio activo cargó claves Meta propias de ZeroAI: el handshake y un POST
firmado sin mensajes respondieron correctamente. El puente Web de LosetasChile
quedó en estado ready tras recargar el backend. Esta prueba no demuestra una
conversación real entregada.

El contexto local activo recupera secciones de la ficha y
datos del contacto de turnos antiguos dentro del límite del modelo. Una afirmación
de cotización ya revisada sin evidencia deriva a revisión humana. Pasaron 998
pruebas Python y 6/6 casos del modelo local; una conversación inventada produjo
una respuesta sin repetir las medidas. El backend respondió a salud, handshake
Meta, POST firmado vacío y estado Web ready. Falta probar una conversación real
de extremo a extremo, sin reintentar el mensaje de entrega incierta del 2026-10-05.
