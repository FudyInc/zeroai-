# Pedido 2026-11-03 · motor-whatsapp: ubicación de la fábrica, línea base y menú de modelos

Origen: chequeo general del 2026-11-03. Lo toma el terminal motor-whatsapp.

1. **Ubicación de la fábrica.** El 31 de octubre un lead real preguntó «¿Cuál es su ubicación?» y el bot respondió «Losetas Chile está ubicada en Santiago, Chile». La dirección ya existe en código (`zero/losetas_polls.py::FACTORY_ADDRESS` y `FACTORY_MAP_URL`, y `zero/config.py::LOSETASCHILE_FLETE_ORIGIN`) y Diego la confirmó: Los Granados 029, La Pintana. La pregunta por la ubicación o la dirección debe responderse con esa dirección y el enlace de Maps, de forma determinista, sin pasar por el modelo. Hay que agregar un caso al set de evaluación.
2. **Línea base.** El 48 % del 2026-10-28 se midió con el arnés sin aislar y sin contar lo que salía por el puente. Hay que volver a correr los 149 casos con el arnés de `14dd14c` y reemplazar ese número.
3. **Menú de modelos** (`PAVER_MODEL_OPTIONS`), con el catálogo como fuente: corregir «Gregioriano» por «Gregoriano» y «Octagonal Piedra» por «Octágono», y agregar Adoquín y Flor de Liz. Antes de cambiar los nombres visibles hay que confirmarlo con Diego.
