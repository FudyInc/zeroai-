# Motor del agente de WhatsApp

**Verificado en código local:** 2026-10-06. **Almacén de producción y conversación
real:** pendientes de comprobar.

El webhook de Meta o Twilio valida el mensaje, obtiene el identificador receptor y, si el
proveedor lo entrega, el nombre del perfil del remitente. El número receptor
determina la empresa antes de buscar al contacto en el CRM: Meta usa el ID del
número y Twilio usa el número receptor. Si dos empresas comparten receptor, el
motor responde solo si el remitente ya existe en una única empresa asociada.
Ante dos coincidencias o un remitente nuevo no elige una por su cuenta.
Con varias empresas, un receptor desconocido
tampoco se asigna a ZeroAI salvo que coincida con el receptor global configurado.
El número global de Twilio conserva ese enrutamiento aunque haya varios vendedores
sin número propio.
Un receptor asignado a un vendedor sin empresa asociada también queda sin respuesta.
Un nombre de perfil
completa un nombre vacío; nunca reemplaza uno ya guardado. Si no hay nombre, el
primer saludo usa «Estimado/a».

Los mensajes y respuestas enviadas quedan en la memoria por empresa y contacto.
CONCIERGE recibe hasta 12 turnos previos para continuar la conversación. Una
respuesta cuyo envío falló no se agrega como turno del agente, y una oferta pendiente
no se marca cumplida si falló el envío.

PoolEdge aún no tiene conectado el cotizador de despacho. Por eso, una consulta de
precio recibe una solicitud de datos sin pasar por el modelo ni adjuntar un total.
La plantilla de `docs/plantilla-presupuesto-pooledge.md` sigue pendiente de integrar.

Estas comprobaciones son del checkout local y de pruebas sin envío real. Falta
verificar la ficha activa, el enrutamiento de números y el comportamiento del motor
en el servicio que atiende WhatsApp antes de considerarlo activo para clientes.
El 2026-10-06, `scripts/verificar_ficha.py --empresa zeroai` encontró 3982 caracteres
en la ficha versionada y ninguna ficha activa en el `state.json` local. Esto no
permite concluir qué ficha usa el servicio de producción.
