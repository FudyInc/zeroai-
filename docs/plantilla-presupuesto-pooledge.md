# Plantilla de presupuesto — PoolEdge

**Estado:** propuesta aprobada por Diego el 2026-09-29. Todavía no está conectada
al cotizador ni al envío de WhatsApp.
**Revisado en código local:** 2026-10-06. La tarifa de despacho y el abono de esta
plantilla siguen pendientes de representación estructurada y cálculo en el
cotizador; el chat y `/api/quote` bloquean el presupuesto final de PoolEdge en
esta rama. PoolEdge no figura como cliente activo en el almacén Supabase verificado.

## Datos del pedido

- Cliente y teléfono: datos de la cotización, no de la ficha de conocimiento.
- Por cada línea: producto, medida, color, cantidad y precio unitario confirmado.
- Despacho: dirección completa y distancia de ruta en auto confirmada por una
  persona. Solo ida, kilómetros redondeados hacia arriba × $1.500.
- Fecha de envío y peso: mostrar solo si están confirmados.
- Abono de fabricación: $10.000; registrar `pendiente` o `recibido`.

## Borrador mientras se revisa el despacho

```text
PRESUPUESTO EN PREPARACIÓN · POOLEDGE
Cliente: [nombre]
Contacto: [teléfono]

[cantidad] × [producto, medida y color] — $[subtotal de línea]
[cantidad] × [producto, medida y color] — $[subtotal de línea]

Despacho a [comuna]: distancia pendiente de revisión manual
Dirección: [dirección completa o «pendiente»]
Fecha de envío: [fecha confirmada o «por confirmar»]
Peso total: [kg confirmados o «por confirmar»]

Estamos revisando el valor del despacho. Te confirmaremos el total final cuando esté listo.
```

El borrador no presenta un total final, porque aún falta el despacho. Si tampoco
hay precio confirmado para algún producto, se indica que su valor está pendiente.

## Presupuesto final con abono recibido

```text
PRESUPUESTO · POOLEDGE
Cliente: [nombre]
Contacto: [teléfono]

[cantidad] × [producto, medida y color] — $[subtotal de línea]
[cantidad] × [producto, medida y color] — $[subtotal de línea]

Productos: $[subtotal de productos]
[Impuestos, según la configuración del catálogo]: $[monto]
Despacho a [dirección completa]: [km de ida redondeados] × $1.500 = $[costo aprobado]
TOTAL DEL PEDIDO: $[productos + impuestos + despacho]
Abono recibido para iniciar fabricación: −$10.000
TOTAL FINAL A PAGAR: $[total del pedido − 10.000]

Fecha de envío: [fecha confirmada o «por confirmar»]
Peso total: [kg confirmados o «por confirmar»]
```

Si el abono está pendiente, el presupuesto muestra el total del pedido y el
abono requerido, sin restar los $10.000 como pago recibido. El descuento se aplica
una sola vez, después de verificar el pago. Nunca se guarda un saldo negativo.

## Condiciones para emitir el final

1. Todos los productos, cantidades, colores y precios unitarios están confirmados.
2. Una persona confirmó la distancia de la ruta en auto desde Los Granados 029,
   La Pintana, hasta la dirección completa. El sistema redondeó hacia arriba
   y calculó el costo a $1.500 por kilómetro de ida.
3. El estado del abono coincide con el pago recibido. Si está pendiente, se muestra
   el total del pedido; si está recibido, el monto destacado abajo es el saldo.
4. El cálculo lo hace el sistema. El agente solo recoge datos y comunica el resultado.
