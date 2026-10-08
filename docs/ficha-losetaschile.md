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
El destino quedó configurado en el backend local el 2026-10-08. Un mensaje
técnico sin datos de clientes fue aceptado y apareció en el grupo. Falta
comprobar el recorrido real de imagen, elección de color y presupuesto con un
mensaje nuevo de prueba. El código aún no está publicado en GitHub ni Vercel.
Diego confirmó el 2026-10-08 que recibió la prueba técnica en el grupo.
El primer mensaje de prueba del cliente no obtuvo respuesta porque el chat
conservaba una pausa de automatización anterior. Esa pausa se liberó y se
verificó; no se reprocesó el mensaje anterior. La prueba posterior se describe
más abajo.

## Medidas al inicio — activo en backend local el 2026-10-08

Diego pidió que, cuando una consulta por bordes de piscina no incluya medidas,
el bot pregunte pronto por el largo y ancho en metros. El flujo determinista
ahora hace esa pregunta antes de pedir el modelo del borde; si el cliente ya
dio las medidas, no las vuelve a solicitar. Una respuesta posterior como
«6x3 m» continúa el pedido hacia la confirmación de modelo, forma y color.
El presupuesto sigue dirigido solo al grupo interno para revisión manual.
Una simulación con la configuración activa preguntó por largo y ancho cuando
faltaban medidas. Una prueba real posterior entregó las medidas en el mensaje
inicial; falta comprobar la pregunta por medidas faltantes desde un chat nuevo.

## Imagen de colores por WhatsApp — verificado el 2026-10-08

El mensaje real con piscina rectangular de 6 × 3 llegó al agente, pero el
primer envío de la imagen falló por una incompatibilidad de `whatsapp-web.js`
con el identificador interno de archivos multimedia. Se ajustó el puente sin
cambiar la dependencia. En una reanudación controlada, WhatsApp confirmó la
imagen con acuse 2; el puente había informado resultado incierto porque buscó
el texto en el cuerpo de la imagen en lugar de su descripción. Se corrigió
también esa comprobación. La imagen no se reenvió: se registró la pregunta de
color tras verificar la entrega. Diego confirmó la recepción y respondió
«gris». El evento se completó y el presupuesto apareció solo en «Presuouesto
losetas ia»: nombre de perfil encima del número, 36 bordes, 4 esquinas,
color gris y total de productos $230.400, con despacho por cotizar. El chat del
cliente no mostró el subtotal. El envío del presupuesto al cliente sigue a
cargo de una persona.

Diego observó que, tras elegir «gris», el bot no respondió en su chat: el
flujo anterior guardaba silencio mientras el presupuesto iba al grupo. El
2026-10-08 se activó un acuse breve que confirma el color **solo después** de
que el grupo acepte el presupuesto, sin importes ni líneas. Se envió una sola
confirmación al chat de prueba existente y WhatsApp mostró acuse 2; el
subtotal siguió ausente del chat del cliente. Falta observar este acuse en un
pedido nuevo procesado íntegramente por el flujo automático.

## Consultas de despacho y ubicación — activo en backend local el 2026-10-08

Diego indicó que se hacen despachos en Santiago y se revisan destinos cercanos
a la Región Metropolitana. Para preguntas de cobertura, incluida «¿despachan
a Los Andes?», el código prepara una respuesta estándar: informa la cobertura
de Santiago, ofrece revisar destinos cercanos y pide dirección escrita o
ubicación actual compartida desde WhatsApp. No confirma Los Andes sin revisión.
Las preguntas por el **precio** del flete mantienen una respuesta aparte que
solicita dirección completa y revisión; los pedidos de productos con flete no
pierden su cotización estructurada.

Diego fijó de forma provisional **$2.000 CLP por km** desde
`Los Granados 029, La Pintana`, ubicación resuelta desde el enlace que entregó.
La tarifa vive en `zero/config.py` y el cálculo exacto en `zero/quotes.py`.
Solo se calcula un importe si una persona aporta distancia por ruta comprobada;
el presupuesto interno muestra origen y tarifa, pero mantiene el flete pendiente
si faltan km. Está pendiente aclarar si se cobra solo ida o ida y vuelta y si
la tarifa se comunica al cliente antes de la revisión. No existe todavía un
servicio de rutas conectado al agente.

Los botones interactivos de la biblioteca WhatsApp Web instalada están
obsoletos. El mensaje usa las dos opciones en texto. El puente ahora convierte
un mensaje de ubicación de WhatsApp en un enlace de mapa con coordenadas para
que se conserve en el borrador interno junto al pedido; antes solo pasaba
`[location]`. También se reconocen respuestas como «Los Andes» o una calle
después de pedir el destino. Una ubicación que actualice el borrador genera
un acuse de datos de entrega sin repetir el color. La suite de 1061 pruebas,
la sintaxis del puente y la simulación de solo lectura con la ficha activa
pasaron el 2026-10-08. El commit `c20c6cc` quedó en `main` local, el backend
reinició con `/api/health` correcto y el puente de LosetasChile reportó
`ready`. Falta probar una ubicación entrante nueva en WhatsApp real; la
ubicación compartida previamente no se reprocesó.

## Encuesta para indicar entrega — activo en backend local el 2026-10-08

Para una consulta por cobertura o precio de despacho, el mensaje ofrece
escribir la dirección o compartir ubicación directamente. Si el envío de ese
mensaje se confirma, el puente prepara debajo una encuesta de una sola
elección: «📍 Compartir ubicación» o «✍️ Escribir dirección». Al seleccionar,
el agente responde con una sola instrucción: abrir `📎/+ → Ubicación → Enviar
ubicación actual`, o escribir calle, número y comuna. El voto **no** comparte
la ubicación por sí mismo. La opción directa del texto permanece disponible
si el envío de la encuesta o su evento de voto no se confirma.

La biblioteca `whatsapp-web.js` 1.34.7 documenta encuestas y el evento
`vote_update`; los botones interactivos siguen obsoletos. El puente limita
esta encuesta a la cuenta de LosetasChile, valida el chat individual y solo
deriva votos de la encuesta de entrega emitida por esa cuenta. En revisión se
corrigió el identificador del votante, que la biblioteca entrega como objeto,
y se añadió una prueba local para esa forma. La suite completa de 1065
pruebas, la prueba Node, la sintaxis del puente y una simulación con la ficha
activa pasaron el 2026-10-08. El commit `efac647` quedó en `main` local; el
backend reinició con `/api/health` correcto y el puente reportó `ready`.
La recepción real del voto y la visualización de la encuesta siguen pendientes
de una prueba nueva en WhatsApp; no se ha enviado una encuesta real todavía.
