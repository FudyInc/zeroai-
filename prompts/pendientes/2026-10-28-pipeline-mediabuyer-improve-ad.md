# Pedido 2026-10-28 · Campañas: anuncios pagados (PIPELINE)

Origen: terminal motor-whatsapp, a pedido de Diego («necesito mejorar el sector de campañas para visualizar y mejorar los posts que ya hemos pagado anuncios»).
Orden: CORE → Pipeline; DASHBOARD en paralelo contra el contrato.

```
[TARGET: 🧠 MOTOR · Pipeline] — si tu sección no es MOTOR · Pipeline, detente y dilo. (No es MOTOR · WhatsApp ni Llamadas.)

OBJETIVO: Que MEDIABUYER sugiera cómo mejorar el texto y la creatividad de UN anuncio pagado, a partir de sus métricas reales, sin publicar ni gastar nada.

CONTEXTO: CORE está agregando GET /api/campaigns/ads con este item por anuncio: {ad_id, ad_name, campaign_name, status, creative{title, body, image_url, call_to_action}, spend, impressions, reach, clicks, ctr, leads, cpl}. zero/agents/mediabuyer.py hoy solo recomienda a nivel campaña. El CPL objetivo vive en config (CHILE["good_cpl_clp"]).

ALCANCE — puedes tocar: zero/agents/mediabuyer.py, tests/test_agents.py.
NO toques: api.py, zero/metaads.py, frontend/, prompts/ (si el prompt mediabuyer.md necesita cambios, descríbelos en el REPORTE para coordinación).

TRABAJO:
1. Una nueva tarea en MediaBuyer (ej. action "improve_ad") que reciba un item con ese contrato y devuelva:
   {"diagnostico": str, "sugerencias": [{"campo": "title"|"body"|"call_to_action"|"imagen", "actual": str, "propuesta": str, "por_que": str}], "metricas_usadas": [...]}
   - El por_que cita métricas del item (CTR, CPL contra el objetivo). No inventes cifras que no vengan en el item.
   - Si el anuncio tiene menos de ~1000 impresiones (umbral en config.py), dilo: "pocos datos para concluir".
2. Un _mock_result determinista con la MISMA forma, usado solo por la suite.
3. Un método del orquestador o un helper que CORE pueda llamar con _agent_op. Sin motor real, CORE responde 503 con el motivo. Coordina el nombre de la función en el REPORTE.

ACEPTACIÓN: python3 -m unittest discover -s tests -t .  en verde. Tests: forma del contrato, pocas impresiones, que no aparezcan cifras ausentes en el item. Una corrida con el motor local (Ollama) sobre un item de ejemplo; pega la salida.

REPORTE: qué cambió, la firma que CORE debe exponer (propuesta: GET /api/campaigns/ads/suggest?client=&ad_id=) y los hallazgos fuera de tu sección.
```
