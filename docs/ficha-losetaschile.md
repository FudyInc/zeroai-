# LosetasChile: cálculo de bordes de piscina

Verificado el 2026-10-07 con Diego durante una prueba real del WhatsApp de
LosetasChile. El catálogo versionado identifica el **borde recto con nariz** y
la **esquina piscina** como piezas de 50 × 50 cm.

Para una piscina rectangular de **6 × 3 m**, Diego confirmó esta regla comercial:
el perímetro es **18 m** y se indican **36 bordes rectos de 50 cm más 4 esquinas**.
Las cuatro esquinas se agregan aparte; no se restan de los 36 bordes rectos.

El motor calcula y guarda esta cantidad para el presupuesto cuando constan el
modelo y ambas medidas. Para lados que no son múltiplos de 50 cm se requiere
confirmar los cortes. El cálculo de piezas no confirma stock ni despacho.

No se envía una frase suelta como «necesitarás 36 bordes y 4 esquinas» ni se
explica el cálculo al cliente. La respuesta comercial es el presupuesto con
sus líneas y **total de productos** calculados desde el catálogo. Mientras
el despacho no tenga valor confirmado, se muestra aparte como «por cotizar»;
el total final con despacho sigue pendiente.

La primera prueba real sí respondió por WhatsApp, pero dijo erróneamente 24
piezas. Una segunda pregunta con la palabra «bordea» eludió el primer filtro y
el modelo volvió a explicar cómo calcular. El 2026-10-07 se añadió ese caso
real a las pruebas y una protección para no enviar instrucciones de cálculo al
cliente. La salida corregida queda sujeta a comprobación real tras publicarla.

El 2026-10-07 Diego confirmó el precio final unitario del esquinero y pidió
cotizar automáticamente los productos del pedido cuando ya estén confirmados
modelo, forma y medidas. El importe se calcula con el catálogo estructurado;
el despacho queda sin importe y se cotiza manualmente. Una ubicación compartida
por WhatsApp Web llega como `[location]`, sin dirección legible, y no permite
calcular ni prometer el despacho. La cotización de productos se presenta como
subtotal separado del despacho.

Verificación de código del 2026-10-07: las consultas por «precios», «cuánto
cuestan» y «valor» usan el subtotal estructurado cuando el pedido está
confirmado. Una pregunta específica por el precio del despacho solicita
revisión de ese cargo sin repetir el subtotal de productos. Esta corrección
quedó activa en el backend local y publicada en `main` el 2026-10-07; una
respuesta real corregida sigue pendiente.

Verificación del 2026-10-07 tras una nueva respuesta real: ante «Necesito
pastelones», el agente inventó «alrededor de 18 pastelones» porque la frase no
activaba el cotizador y llegaba al modelo. Diego aclaró que, con el pedido ya
confirmado, las cantidades son internas y la respuesta debe ser el presupuesto
con total. La corrección local usa el pedido previo para armar ese presupuesto;
si faltan modelo o medidas, solicita el dato faltante. Una cifra de piezas
generada por el modelo sin presupuesto se deriva a revisión. Falta publicar y
comprobar la nueva respuesta real.

## Color y revisión interna — verificado en código local el 2026-10-08

Diego entregó una imagen con la gama de **anaranjado, blanco, rojo, crema,
beige, gris y amarillo** para bordes de piscina. La imagen versionada está en
`frontend/public/catalog/losetaschile/gama-bordes-piscina.jpeg`. Diego confirmó
que el color no cambia los precios unitarios; la disponibilidad de cada color
todavía debe revisarse. Cuando el modelo de borde, la forma y las medidas ya
están claros, el flujo local envía la imagen y pregunta qué color prefiere el
cliente antes de preparar el presupuesto.

El presupuesto para LosetasChile es un **borrador interno**: lleva el nombre de
perfil de WhatsApp si existe y, debajo, el número del cliente. Si no existe
nombre de perfil, omite esa línea y conserva el número. Incluye color elegido,
líneas calculadas desde el catálogo y total de productos; el despacho queda por
cotizar. Se dirige a un grupo de revisión separado y una persona decide el
envío al cliente. El grupo «Losetas Diego» visto en la cuenta no es el destino
de presupuestos. Diego creó «Presuouesto losetas ia», y el 2026-10-08 se
verificó que aparece como grupo distinto en la cuenta Web de LosetasChile.
Falta configurar ese destino en el servicio, desplegar el flujo y comprobar
un envío real. El código y las pruebas de este flujo son locales.
