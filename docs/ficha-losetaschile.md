# LosetasChile: cálculo de bordes de piscina

Verificado el 2026-10-07 con Diego durante una prueba real del WhatsApp de
LosetasChile. El catálogo versionado identifica el **borde recto con nariz** y
la **esquina piscina** como piezas de 50 × 50 cm.

Para una piscina rectangular de **6 × 3 m**, Diego confirmó esta regla comercial:
el perímetro es **18 m** y se indican **36 bordes rectos de 50 cm más 4 esquinas**.
Las cuatro esquinas se agregan aparte; no se restan de los 36 bordes rectos.

El motor calcula esta cantidad solo cuando el cliente pregunta por piezas del
borde recto con nariz y constan el modelo y ambas medidas. Para lados que no
son múltiplos de 50 cm se requiere confirmar los cortes. Esto no confirma
precio, stock, despacho ni la cotización final.

La respuesta al cliente debe ser breve y dar el resultado directamente, por
ejemplo: «Para tu piscina de 6 × 3 m: 36 bordes rectos de 50 cm más 4 esquinas».
No debe explicar al cliente que calcule el perímetro por su cuenta.

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
