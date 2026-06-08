# Estado de integraciones — qué es mock, qué es real, qué necesita cada cosa

Mapa para entender ZeroAI de un vistazo (útil para onboarding del socio).
Hay **dos tipos de mock**: el **cerebro** (IA) y los **canales/datos externos**. No todo
depende de Anthropic.

## ✅ Ya es REAL (funciona hoy, sin costo extra)
| Componente | Estado |
|---|---|
| CRM en la nube (Supabase) | real |
| Estado/ICP en la nube | real |
| Login de agencia (auth) | real |
| Email **saliente** (SMTP/Gmail) | real — ya conectado |
| Escalabilidad (carga por cliente, paginación) | real |

## 🧠 Mock = CEREBRO IA → autónomo con un MODELO (Anthropic **o** local gratis)
Estos corren en mock (determinista) y se vuelven inteligentes al enchufar un modelo.
**No es solo Anthropic**: un modelo **local (Ollama)** los activa **gratis**.

| Agente | Qué hace cuando es real |
|---|---|
| QUALIFIER | califica leads con criterio real (hoy es plantilla) |
| PITCHWRITER | escribe el pitch creativo desde tu contexto |
| CONCIERGE | responde WhatsApp/dudas como humano |
| MEDIABUYER | gestiona campañas (analiza y recomienda) |
| OUTREACH / TRACKER | primer toque y follow-ups con criterio |
| ANALYST | comenta el forecast |

→ Activar: `ANTHROPIC_API_KEY` (pago) **o** `LOCAL_MODEL` + Ollama (gratis).

## 🔌 Mock = CANAL/DATO externo → real con TU cuenta (no con Anthropic)
Estos necesitan credenciales de **otros** servicios, no del modelo.

| Integración | Qué necesita | Costo |
|---|---|---|
| WhatsApp (enviar/recibir) | Meta WhatsApp Business (token) | setup gratis; envío con límites |
| Meta Ads (campañas/insights/gestión real) | token + cuenta Meta | cuenta nueva tiene cooldown; ads = tu presupuesto |
| Discovery de leads reales | proveedor con key (o DuckDuckGo gratis parcial) | pago para cobertura |
| Voz / llamadas | ElevenLabs + Vapi | pago |

## En una frase
**Autónomo = cerebro (un modelo: Anthropic o local gratis) + canales conectados (cada
uno con su cuenta).** Hoy todo está construido mock-first: enchufas credenciales y deja
de simular, sin reescribir código. Política: lo de pago se posterga (ver
[zero-cost-policy] en memoria); el cerebro puede ser **local y gratis**.
