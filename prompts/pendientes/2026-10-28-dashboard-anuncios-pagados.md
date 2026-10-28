# Pedido 2026-10-28 · Campañas: anuncios pagados (DASHBOARD)

Origen: terminal motor-whatsapp, a pedido de Diego («necesito mejorar el sector de campañas para visualizar y mejorar los posts que ya hemos pagado anuncios»).
Orden: CORE → Pipeline; DASHBOARD en paralelo contra el contrato.

```
PASO 0: git fetch && git rebase origin/main antes de editar.

[TARGET: 🖥️ DASHBOARD] — si tu sección no es DASHBOARD, detente y dilo.

OBJETIVO: Que en Campañas el operador vea cada anuncio/post pagado con su creatividad y sus resultados, y pueda pedir sugerencias para mejorarlo.

CONTEXTO: Extiende frontend/src/pages/Campanas.jsx; no crees una pestaña nueva. CORE expone GET /api/campaigns/ads?client=X → {source: "live"|"unavailable", reason, currency, items:[{ad_id, ad_name, campaign_name, status, post_id, creative{title, body, image_url, thumbnail_url, call_to_action}, spend, impressions, reach, clicks, ctr, leads, cpl}]}. Sugerencias: GET /api/campaigns/ads/suggest?client=&ad_id= → {diagnostico, sugerencias[{campo, actual, propuesta, por_que}]}, o 503 con motivo. Si los endpoints aún no están en main, construye contra este contrato y muestra el estado "no disponible".

ALCANCE — puedes tocar: frontend/src/pages/Campanas.jsx y componentes nuevos en frontend/src/components/ si hacen falta.
NO toques: api.py, zero/, prompts/, web/.

TRABAJO:
1. Una sección "Anuncios pagados" bajo los KPIs actuales. Cada anuncio, en tarjeta o fila, muestra: miniatura, título, texto (truncado y expandible), campaña, estado, gasto, impresiones, clics, CTR, leads y CPL. El CPL se colorea contra el objetivo solo si la API lo trae; no lo hardcodees en el front.
2. Orden por defecto: más gasto primero. Opción de ordenar por CPL; los anuncios sin leads van al final y muestran "—", no $0.
3. El botón "Sugerir mejoras" en cada anuncio llama a /suggest y muestra el texto actual al lado de la propuesta, con el por qué. Con 503, muestra el motivo tal cual. Nada de publicar ni editar desde aquí: el texto es para copiarlo.
4. Con source="unavailable", la sección se ve vacía con el reason visible. Nunca datos de ejemplo.
5. Mantén el estilo editorial existente y usa las primitivas compartidas (Card, Button, Eyebrow, SectionTitle). Paleta ZEROAI. Solo escritorio.

ACEPTACIÓN: npm run build sin errores. python3 -m unittest discover -s tests -t .  en verde (incluye el test anti-rutas-duplicadas). Captura de Campañas con datos live, o con el estado "no disponible" y su motivo, que Diego pueda abrir.

REPORTE: qué cambió, la captura y los hallazgos fuera de DASHBOARD.
```
