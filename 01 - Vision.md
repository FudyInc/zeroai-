# Vision

## Qué es

**ZeroAI (ZERO)** es un orquestador **multi-agente** de **generación de leads B2B**. ZERO es el cerebro: compone tareas en JSON, las reparte a sub-agentes especializados, valida la salida contra una vara estricta de "lead calificado", registra cada cambio de estado y ensambla el entregable para el cliente.

## Misión

> Entregar a un cliente **leads B2B calificados y confiables, listos para contactar**.

Esta es la vara con la que se decide todo: cada feature existe solo si acerca al producto a cumplir esa promesa. Ver [[06 - Roadmap]] y la disciplina de alcance.

## Propuesta de valor

- **Corre en cualquier lado.** Todos los agentes hablan el **mismo contrato JSON** sin importar el backend. El destino de producción es un **modelo local** (Qwen/Llama) en tu propia máquina — sin key, sin costo por token. Ver [[03 - Backends]].
- **Mock-first.** Se construye y prueba contra mocks fieles al contrato; las integraciones reales (LLM, scraping, correo, APIs) se enchufan después en su frontera. El mock sintetiza leads/scores deterministas para ver el pipeline completo sin gastar tokens.
- **Política separada del mecanismo.** Las reglas de negocio (tiers, gate, cadencia, forecast) viven en `zero/config.py`; la lógica solo las aplica. Ver [[05 - Modelo de Negocio]].
- **Sistema de registro real.** Cada lead queda en un **CRM** durable con su etapa y su historial completo de interacciones. Ver [[04 - CRM y Pipeline de Ventas]].

## Cómo llega al prospecto

ZERO descubre empresas, las califica contra el ICP del cliente, valida el contacto, escribe el primer mensaje y mantiene la cadencia de seguimiento — por **email, WhatsApp, llamada en frío** y, según el tier, LinkedIn / SDR AI. Ver [[02 - Arquitectura]].

> [!note]
> Equipo de 1 (más un socio). Se prioriza robustez y claridad del núcleo sobre cantidad de features. Cada feature es un pasivo de mantención.
