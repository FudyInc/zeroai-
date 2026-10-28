# Pedido 2026-10-28 · Campañas: anuncios pagados (CORE)

Origen: terminal motor-whatsapp, a pedido de Diego («necesito mejorar el sector de campañas para visualizar y mejorar los posts que ya hemos pagado anuncios»).
Orden: CORE → Pipeline; DASHBOARD en paralelo contra el contrato.

```
PASO 0: tu rama va ~125 commits atrás de main. Antes de editar: git fetch && git rebase origin/main (si hay WIP, commitéalo primero).

[TARGET: ⚙️ CORE] — si tu sección no es CORE, detente y dilo.

OBJETIVO: Que la API entregue, por cada anuncio pagado de Meta de un cliente, su post/creatividad y sus métricas reales, para que Campañas pueda mostrarlos.

CONTEXTO: Hoy zero/metaads.py::MetaAds.campaigns solo pide insights a nivel campaña (campaign_id, spend, actions). Falta el nivel anuncio. Leer insights de anuncios ya pagados no cuesta (zero-cost-policy OK). El token ya existe (META_ADS_TOKEN / META_AD_ACCOUNT_ID y tokens por cliente vía client_token()). Solo lectura: nada de pausar, editar ni crear.

ALCANCE — puedes tocar: zero/metaads.py, api.py (solo endpoints de /api/campaigns*), zero/config.py si aparece algún número de negocio nuevo, tests/test_metaads.py, tests/test_api_http.py.
NO toques: frontend/, zero/agents/, prompts/, zero/orchestrator.py.

TRABAJO:
1. MetaAds.ads(client_id, cfg, since=None) contra Graph v20.0 (reusa _graph/_graph_pages/_amount/_lead_count):
   - GET {account}/ads fields=id,name,campaign_id,campaign{name},effective_status,creative{title,body,image_url,thumbnail_url,call_to_action_type,effective_object_story_id}
   - GET {account}/insights level=ad fields=ad_id,spend,impressions,reach,clicks,ctr,actions (date_preset=maximum o time_range si viene since)
   - Une por ad_id. CPL = spend/leads, con None si leads == 0 (nunca dividir por cero ni inventar 0).
   - Misma regla de moneda que campaigns(): si la cuenta no es CLP, decláralo; no conviertas en silencio.
2. MockMetaAds.ads con la MISMA forma de datos. Úsalo SOLO en la suite: el endpoint no lo sirve como real.
3. GET /api/campaigns/ads?client=X[&since=YYYY-MM-DD] → contrato:
   {"source": "live"|"unavailable", "reason": str|null, "currency": "CLP",
    "items": [{"ad_id","ad_name","campaign_id","campaign_name","status","post_id",
               "creative": {"title","body","image_url","thumbnail_url","call_to_action"},
               "spend","impressions","reach","clicks","ctr","leads","cpl"}]}
   Sin token o con error de Graph → 200 con source="unavailable", items=[] y reason legible (ej. "Meta no conectado para este cliente", o el mensaje de Graph). NUNCA items de mock.
4. Respeta el aislamiento por cliente: usa el token del cliente pedido y nunca el de otro (ver docs/CLIENT_ISOLATION.md).

RESTRICCIONES: solo stdlib. Revisa git status antes de editar (hay otras terminales trabajando). Los números de negocio van en config.py.

ACEPTACIÓN:
- python3 -m unittest discover -s tests -t .  en verde (el único error tolerado es tests.test_visual_catalog).
- Tests nuevos: unión ads+insights, CPL None con 0 leads, sin token → unavailable sin items, el token de un cliente no se usa para otro.
- Una llamada real de solo lectura: curl "localhost:8800/api/campaigns/ads?client=<cliente con token>" devuelve source=live con al menos un anuncio, o un reason exacto de Graph. Pega la salida, sin el token.

REPORTE: qué cambió, la salida del curl y los hallazgos fuera de CORE (repórtalos, no los arregles).
```
