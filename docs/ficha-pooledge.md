# PoolEdge — reglas para presupuestos por WhatsApp

**Estado:** contenido aprobado para preparar la ficha; no cargado en el almacén activo.
**Confirmado por Diego:** 2026-09-29.
**Verificación de código:** 2026-10-06. El motor y `/api/quote` impiden emitir un
presupuesto final para `pooledge` mientras no exista cálculo de despacho revisado.
La plantilla aún no está conectada. Una lectura del almacén Supabase de producción
el 2026-10-06 no encontró a PoolEdge como cliente registrado; este código tampoco
está desplegado allí. Las tarifas y el
abono confirmados se documentan en `docs/plantilla-presupuesto-pooledge.md`; antes
de activar esta ficha deben quedar como datos estructurados en el catálogo y el
cotizador, con el cálculo comprobado.

Este archivo contiene reglas generales del negocio. Los datos de un comprador y de
un pedido concreto pertenecen a la cotización, no a la base de conocimiento.

<!-- INICIO FICHA -->

PRESUPUESTOS DE POOLEDGE

UBICACIÓN DE POOLEDGE

La ubicación que PoolEdge comparte con sus clientes es Los Granados 029, La Pintana,
Región Metropolitana, Chile. Enlace directo de Google Maps:
https://maps.app.goo.gl/yd4CKEr1bqi7RwsZA

Si preguntan dónde está PoolEdge, dónde se encuentran, dónde quedan, cuál es su
dirección o piden la ubicación, responde con la dirección y comparte ese enlace.
No inventes horarios de atención, disponibilidad de retiro ni indicaciones de ruta.

Para presupuestar bordes de piscina, registra cada producto por separado con su tipo,
medida, color, cantidad y precio unitario vigente. Las esquinas son una línea distinta
de los bordes rectos. No inventes precios, disponibilidad, peso, fecha de envío ni
costo de despacho. Si falta un dato necesario, pide confirmarlo antes de presentar
un total final.

El presupuesto debe identificar al cliente, detallar productos y cantidades, indicar
despacho y mostrar el total del pedido. La dirección de despacho debe estar completa
antes de solicitar la revisión del envío. El despacho se calcula con la tarifa
vigente del cotizador a partir de la ruta en auto desde Los Granados 029, La Pintana,
hasta la dirección de entrega. Se cuenta solo la ida y se redondean los kilómetros
al entero superior. La distancia de la ruta y el costo resultante deben ser
confirmados por una persona antes del presupuesto final. El agente no estima
kilómetros ni tarifas por su cuenta.
Si la fecha o el peso no están confirmados, muéstralos como pendientes y no como
datos definitivos.

El abono para iniciar fabricación forma parte del precio total del pedido: no se
suma como cargo adicional. Registra si está pendiente o recibido. Solo cuando el
pago esté confirmado, descuenta el abono registrado del total del pedido y muestra
al final, de forma destacada, el TOTAL FINAL A PAGAR. Ese monto es el saldo que el
cliente debe pagar después del abono. Si el abono aún está pendiente, no muestres el
descuento como aplicado ni llames «saldo final» a un monto que lo descuenta.

Un presupuesto con precio de producto, costo de envío o cantidad sin confirmar es
un borrador. No lo envíes como presupuesto final. Cuando falte despacho, recoge la
dirección completa y deriva la cotización del envío a revisión manual. Los cálculos
de productos, despacho, abono y saldo los hace el sistema a partir de datos
estructurados; el agente no calcula cifras de memoria.

<!-- FIN FICHA -->
