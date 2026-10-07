# Motor del agente de WhatsApp

**Código activo y pruebas locales:** 2026-10-07. El backend reinició con
`main` en `749dbcd` y respondió a `/api/health`; el puente Web quedó `ready`.
El dashboard se publicó en Vercel producción el mismo día.
**Almacén de producción:** ficha ZeroAI y conexión Meta comprobadas.
**Conversación real:** Diego confirmó respuestas en el WhatsApp de LosetasChile
el 2026-10-06 23:41 Chile, antes de la corrección del cálculo de bordes.
El catálogo activo de LosetasChile ya incluye el esquinero; el subtotal de
productos de un pedido 6 × 3 m se calculó con historial y precios reales en una
simulación sin envío. Faltan una respuesta real de ese subtotal por WhatsApp y
una conversación real de ZeroAI por Meta.

**Comprobación 2026-10-07:** el backend respondió a `/api/health` con el
subtotal de productos y la segunda corrección de bordes ya en `main`. Después
se integró `6147176`, que mejora el contexto y la revisión de consultas. La
revisión del cotizador encontró dos consultas de precios no cubiertas; su
corrección está solo en `motor-whatsapp`, pendiente de publicación y prueba real.

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
