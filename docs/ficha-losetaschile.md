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

La prueba real anterior a esta corrección sí respondió por WhatsApp, pero dijo
erróneamente 24 piezas. La regla nueva queda sujeta a otra comprobación en
producción tras publicar el cambio.
