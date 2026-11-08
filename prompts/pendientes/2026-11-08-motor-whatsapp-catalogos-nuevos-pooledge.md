# Pedido 2026-11-08 · motor-whatsapp (eval-whatsapp): catálogos nuevos de PoolEdge

Origen: el 2026-11-08 Diego le pasó a CORE el contexto del proyecto «Catálogos de productos mejorados» (Claude Design) para armar la landing `pooledgecl`. Pidió que el agente de WhatsApp se adapte a ese mismo material: **estos son los catálogos nuevos**.

Fuente del contexto: `/mnt/c/Users/WinterOS/Pictures/anuncios/Contexto proyecto PoolEdge.md` (léelo completo antes de empezar).

Archivos nuevos (los dejó CORE hoy a las 16:44, fuera del repo):
- `/home/diego/pooledgecl/catalogos/catalogo-bordes-pooledge.pdf` — 3,9 MB, 11 páginas: portada, fabricación + instalación (antideslizante / atérmico), fichas de Borde Ballena, Borde Recto con Nariz, Extensión de Borde y Esquina Piscina, contacto con QR.
- `/home/diego/pooledgecl/catalogos/catalogo-pastelones-pooledge.pdf` — 6,0 MB, unas 15 páginas (el contexto dice 14; verifícalo): portada, fabricación, «La gama» 40×40 y 50×50, fichas por diseño (madera, laja, adoquín y más), contacto con QR.

Qué hace hoy el agente (origin/main `81f112a`):
- `whatsapp-web-bridge/catalog-document.js` arma el PDF al vuelo, **con precios**, y solo con pastelones de 40×40 (5 modelos).
- `zero/losetas_polls.py::PAVER_MODEL_OPTIONS` = Laja española, Ladrillo cruzado, Sol, Sol rústico, Gregoriano.
- El orquestador manda `catalog_document {category, pricing}` (`zero/orchestrator.py` ~1268, 1404, 1446, 2119).

```
PASO 0: git status. Tienes cambios sin commitear en scripts/evaluar_linea_base.py y tests/test_evaluar_linea_base.py: ciérralos (commit) antes de empezar. Luego git fetch && git rebase origin/main.

[TARGET: 🟢 MOTOR-WHATSAPP] — si tu sección no es esa, detente y dilo.

TAREA 1 — Enviar los catálogos nuevos
- Copia los dos PDF al repo (no enlaces a /home/diego/pooledgecl: ese directorio es de CORE y puede cambiar).
- Cuando el cliente pide catálogo de bordes o de pastelones, el puente envía ESE PDF tal cual. Se acaba el PDF generado.
- Regla nueva del negocio: los precios NO van en el material; se dan por WhatsApp en texto porque se actualizan. El flujo de precios que hoy viaja en `pricing` tiene que llegar al cliente como mensaje, no perderse.
- Mantén la confirmación de envío que hoy compara el título/pie del documento.
- Las fotos sueltas que manda `send_catalog_image` siguen igual salvo que choquen con el catálogo; si chocan, repórtalo.

TAREA 2 — Que el agente diga lo mismo que el catálogo
- Atributos: antideslizantes y atérmicos (no se calientan al sol); hormigón de alta resistencia.
- Despacho: toda la Región Metropolitana y regiones cercanas. Compara con lo que responde hoy (SHIPPING_COVERAGE_REPLY y afines) y alinea.
- Medidas exactas, peso y colores se confirman con cada cliente: el bot no inventa ninguno.
- Pastelones 50×50 y los diseños del catálogo que no están en PAVER_MODEL_OPTIONS: NO agregues precio ni nombre visible sin confirmarlo con Diego. Lista las diferencias exactas (catálogo vs menú) en el reporte y pregúntale.
- Marca: los catálogos dicen PoolEdge; el bot todavía dice «Losetas Chile» en algunos textos (p.ej. orchestrator.py ~2201). No cambies nombres visibles sin confirmarlo con Diego; repórtalos.

TAREA 3 — Mensajes de entrada nuevos
El QR del catálogo abre WhatsApp con «Hola PoolEdge, vi el catálogo y quiero cotizar», y la web con «Hola PoolEdge, vi la web y quiero cotizar». Los anuncios de Meta (Boost → mensajes a WhatsApp) también llegan acá. El agente debe tratarlos como un lead que ya vio el catálogo: saludar y avanzar a cotizar, sin reenviar el catálogo de entrada.

TAREA 4 — Evaluación
- Agrega casos al set de evaluación para: pedido de catálogo de bordes, de pastelones, los dos mensajes de entrada del QR y la web, y una pregunta por 50×50.
- tests.test_visual_catalog es el error que se tolera hoy: con el PDF generado fuera, adáptalo o retíralo, y explica qué hiciste.
- Corre la línea base con el arnés aislado (14dd14c) y compara contra la última medición.

ALCANCE: whatsapp-web-bridge/ (catálogo), zero/losetas_polls.py, zero/orchestrator.py (solo el flujo de catálogo y precios), zero/config.py (solo textos y reglas de catálogo/despacho), scripts/evaluar_linea_base.py, tests/.
NO toques: api.py, frontend/, zero/metaads.py, prompts/, /home/diego/pooledgecl (es de CORE).

PRUEBA: NUNCA envíes a un cliente real. Prueba con el arnés aislado y con un envío al grupo de revisión o a un número propio, y pega la salida. Antes de reiniciar el puente en producción, avisa a Diego.

ACEPTACIÓN: la suite en verde; los dos PDF salen por el puente en una prueba real a un chat propio; la línea base no empeora.

REPORTE: qué cambió, la salida de la prueba de envío, las diferencias catálogo vs menú y los textos de marca que esperan decisión de Diego.
```
