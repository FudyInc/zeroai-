# Motor del agente de WhatsApp

**Verificado en código local:** 2026-10-06 tras integrar `origin/main` y los
cambios del checkout activo en una copia aislada. **Almacén de producción:** ficha
ZeroAI y conexión Meta comprobadas el 2026-10-06. **Conversación real con este
código:** pendiente.

El código integrado admite Meta Cloud y sesiones WhatsApp Web asignadas por
negocio. El envío real exige credenciales propias del negocio; la migración de
ZeroAI desde las variables globales aún debe verificarse antes del despliegue.

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
CONCIERGE recibe hasta 12 turnos previos para continuar la conversación. Una
respuesta cuyo envío falló no se agrega como turno del agente, y una oferta pendiente
no se marca cumplida si falló el envío. Con `OUTBOX_LIVE=1`, la falta de
credenciales Meta produce un error de envío, no un resultado simulado como enviado.

PoolEdge aún no tiene conectado el cotizador de despacho. Por eso, una consulta de
precio recibe una solicitud de datos sin pasar por el modelo ni adjuntar un total.
La plantilla de `docs/plantilla-presupuesto-pooledge.md` sigue pendiente de integrar.
El cotizador directo `/api/quote` también rechaza el presupuesto de PoolEdge
hasta que exista la revisión del despacho.

Estas comprobaciones son del checkout local y de pruebas sin envío real. Falta
verificar el enrutamiento y una conversación real con la versión integrada antes
de considerarla activa para clientes. El backend en `/home/diego/zeroai` está
activo pero conserva cambios locales sin commit; esta rama no se ha desplegado allí.
Una lectura de solo metadatos del almacén Supabase de ese servicio encontró la ficha
activa de ZeroAI idéntica a la versionada (3982 caracteres), número y token Meta
configurados y el número reconocido por Graph API. PoolEdge no está registrado
como cliente activo. El vendedor de ZeroAI conserva un ID semilla antiguo en el
almacén; `credentials_for` lo ignora y usa el número global configurado. No se
mostraron secretos, números ni datos de leads durante esta comprobación.
