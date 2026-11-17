# Campañas PoolEdge — auditoría del 16 de noviembre de 2026

Estado: corrección en worktree `campaign-ads-all-period`, pendiente de integración y publicación. Las consultas reales fueron solo lectura; no se modificaron campañas ni se enviaron mensajes. No se almacenaron nombres ni identificadores de campañas.

## Hallazgos comprobados

- Meta conserva 162 campañas como `ACTIVE`. Ese estado por sí solo no prueba que estén vigentes.
- De 160 conjuntos habilitados, 159 ya terminaron. Al cruzar campaña habilitada, conjunto habilitado vigente y anuncio habilitado, queda 1 campaña activa en el momento de la lectura. Otra de las 2 con gasto mensual ya finalizó.
- La implementación corregida devuelve 1 activa y 161 finalizadas. Comparada con producción conserva la cantidad de campañas y los totales de gasto y consultas mensuales.
- El filtro inicial de campañas volvía de Activas a Todas mediante un efecto al cargar o cambiar negocio.
- Los gráficos estaban plegados en Detalle; además el gráfico de consultas dependía indebidamente de que hubiera datos de gasto diario. Un error de la serie se ocultaba silenciosamente.
- Meta entregó seis puntos de gasto diario entre el 10 y el 15 de noviembre. No se rellenan fechas omitidas con ceros sin evidencia.

## Correcciones

La vigencia se comprueba en backend con fechas de inicio y fin del conjunto y anuncios activos. Las consultas adicionales paginan en modo estricto para evitar conteos parciales. Se distinguen campañas activas, finalizadas, programadas, pausadas y sin entrega activa. Se mantiene el histórico para que el gasto mensual no desaparezca cuando termina una campaña.

La tabla inicia en Activas. Los gráficos quedan visibles, independientes, con fechas legibles, escala monetaria y aviso recuperable cuando falla la serie. El estado vacío se distingue de un error. Tus anuncios muestra por defecto anuncios activos de campañas vigentes y conserva el histórico como consulta explícita; los anuncios sin gasto no forman parte de la API de anuncios pagados.

## Mejoras sugeridas

1. Unificar el selector de fechas: hoy el resumen y las consultas cubren el mes, el gasto diario siete días y las tarjetas permiten el historial. Etiquetar el alcance evita comparar períodos distintos.
2. Mostrar la hora de última lectura de Meta y permitir actualizar toda la sección para reconocer datos antiguos sin recargar la página.
3. Incorporar en un trabajo posterior anuncios vigentes sin gasto. La API actual parte de Insights pagados; un anuncio nuevo sin gasto puede estar activo aunque todavía no aparezca como tarjeta.
4. Añadir comparación de costo por consulta y consultas contra el período anterior únicamente cuando ambas ventanas tengan datos completos.

## Validación

Las pruebas de regresión cubren fin de vigencia, inicio futuro, ausencia de anuncios activos, conjuntos ausentes, fechas inválidas y conjuntos vigentes/vencidos dentro de una misma campaña. El backend entrega los IDs de anuncios vigentes para filtrar también ese último caso. La lectura real del backend corregido confirmó el conteo y la conservación de los totales. Suite completa: 1775 pruebas Python y 38 pruebas frontend aprobadas; compilación aprobada con aviso de bundle grande. Chromium con datos sintéticos verificó filtros, gráficos independientes, fallo/reintento y vista móvil. Estas comprobaciones no equivalen a un despliegue.
