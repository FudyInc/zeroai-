# Roadmap

Estado vivo (resumen del `README.md`, `CLAUDE.md` y `docs/roadmap.md`). Para detalle por integración: `docs/estado-integraciones.md`.

## Estado actual — qué está real

Los cinco agentes del núcleo son reales en **todos** los backends (mock · local · live):

- [x] **ZERO** orquesta (dispatch, gate, log, deliverable).
- [x] **PROSPECTOR** descubre (mock/LLM y **web real** vía DuckDuckGo, sin key).
- [x] **Enriquecimiento de decision-maker** (lee about/team, extrae `Nombre — Rol`; precision-first, deja `"por verificar"` sin evidencia dura). On por defecto; `--no-enrich` para saltar.
- [x] **QUALIFIER** puntúa (0–100 + ICP).
- [x] **OUTREACH** escribe el primer toque.
- [x] **TRACKER** corre la cadencia (nudge → value → breakup).
- [x] **ANALYST** proyecta el pipeline desde la actividad registrada.
- [x] Cada lead aterriza en el **[[04 - CRM y Pipeline de Ventas|CRM]]** con etapa e historial.
- [x] Agentes de extensión: **CONCIERGE** (respuestas), **MEDIABUYER** (Meta Ads), **PITCHWRITER** (pitch).
- [x] Dashboard web (`api.py` + `frontend/`), datos en la nube (Supabase), config persistente.
- [x] Corre **local** como fuente de verdad, con backend, túnel y dashboard arrancando solos en el boot (systemd). Ver [[09 - Otros]].

## Próximos pasos

- [ ] **Proveedor de discovery/enrichment con key** (Brave / SerpAPI / data provider) para alta cobertura — entra con la misma firma de `zero/discovery.py`, sin tocar PROSPECTOR.
- [x] **Detección de respuestas** para auto-cerrar secuencias de seguimiento cuando el lead responde (✅ junio 2026: `zero/inbox.py` + mock/file/IMAP, cierra la loop automáticamente).
- [x] Mejorar la **discovery gratis** (DuckDuckGo) — minería de directorios, fallback a /contacto, mejores señales de email/teléfono. ✅ junio 2026: 6/6 leads reales con contacto.
- [ ] Afinar **prompts** de los agentes (concierge, pitch, mediabuyer).

## Pendientes de pago (pospuestos por la política de costo cero)

- [ ] Key de **Anthropic** (modo `--live` en prod) — mientras tanto, mock/local.
- [ ] **Meta Ads** insights / ejecutar-plan (gasto real).
- [ ] **Vapi** (llamadas) y **ElevenLabs** (voz) a volumen.
- [ ] **Email / WhatsApp** a volumen.
- [ ] **Dominio** propio + host de pago (hoy se corre local).

> [!todo]
> Mantener `docs/roadmap.md` y `docs/estado-integraciones.md` como el detalle vivo; esta nota es el resumen navegable.
