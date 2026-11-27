# Vision

## Qué es

**ZeroAI (ZERO)** vende **agentes de WhatsApp plug-and-play para pymes**: el negocio contrata, sube su catálogo y sus preguntas frecuentes, y su agente responde, cotiza y deriva a una persona cuando hace falta. Por dentro sigue siendo un orquestador **multi-agente** que habla un mismo contrato JSON.

## Misión

> Que un negocio nuevo tenga su **agente de WhatsApp respondiendo bien en horas, no días**.

Decisión del 2026-11-27 (antes la misión era entregar leads B2B calificados). Orden de producto:
1. **Agente de WhatsApp plug-and-play** — el producto.
2. **Contenido de marketing por empresa** — campañas, reels, videos.
3. **Agentes de llamada.**
4. **Leads** como extra del paquete, más B2C que B2B.

Esta es la vara con la que se decide todo: cada feature existe solo si acerca al producto a cumplir esa promesa. Ver [[06 - Roadmap]] y la disciplina de alcance.

## Propuesta de valor

- **Corre en cualquier lado.** Todos los agentes hablan el **mismo contrato JSON** sin importar el backend. El destino de producción es un **modelo local** (Qwen/Llama) en tu propia máquina — sin key, sin costo por token. Ver [[03 - Backends]].
- **Mock-first.** Se construye y prueba contra mocks fieles al contrato; las integraciones reales (LLM, scraping, correo, APIs) se enchufan después en su frontera. El mock sintetiza leads/scores deterministas para ver el pipeline completo sin gastar tokens.
- **Política separada del mecanismo.** Las reglas de negocio (tiers, gate, cadencia, forecast) viven en `zero/config.py`; la lógica solo las aplica. Ver [[05 - Modelo de Negocio]].
- **Sistema de registro real.** Cada lead queda en un **CRM** durable con su etapa y su historial completo de interacciones. Ver [[04 - CRM y Pipeline de Ventas]].

## El pipeline de leads (extra del paquete)

ZERO descubre empresas, las califica contra el ICP del cliente, valida el contacto, escribe el primer mensaje y mantiene la cadencia de seguimiento — por **email, WhatsApp, llamada en frío** y, según el tier, LinkedIn / SDR AI. Ver [[02 - Arquitectura]].

> [!note]
> Equipo de 1 (más un socio). Se prioriza robustez y claridad del núcleo sobre cantidad de features. Cada feature es un pasivo de mantención.
