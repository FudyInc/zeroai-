# Modelo de Negocio

La **política** vive en `zero/config.py` (`TIERS`): qué recibe cada tier, su límite de leads, su tipo de scoring y sus canales. Cambiar la promesa comercial = cambiar config, no lógica.

## Tiers

| Tier | Segmento | Precio (CLP/mes) | Leads/mes | Scoring | Canales |
|---|---|---|---|---|---|
| **STARTER** | Básico | 50.000 | 50 | `basic` (ICP genérico) | email · whatsapp |
| **GROWTH** | Pro | 200.000 | 200 | `advanced` (ICP del cliente) | + cold_call |
| **SCALE** | Full | 500.000 | 500 | `intent` (ICP + intención de compra) | + linkedin |
| **ENTERPRISE** | Custom | negociado | negociado | `vertical` (modelo por vertical) | + sdr_ai |

- `price_clp` = lo que el cliente paga al mes → es el **MRR** de la agencia. ENTERPRISE tiene `price_clp = None` (custom/negociado).
- `leads_per_mo = None` en ENTERPRISE significa "custom".
- El `--count` del CLI se **capa** por el límite mensual del tier. Ver [[07 - CLI y Comandos]].
- Niveles de scoring crecientes: `basic → advanced → intent → vertical`. Más tier = más señales de calificación. Ver [[04 - CRM y Pipeline de Ventas]].

## MRR

El dashboard (`api.py`, endpoint `/api/accounts`) suma el `price_clp` del tier de cada cliente con plan activo para mostrar el **MRR** (lo que factura la agencia al mes).

## Finanzas de la agencia

`zero/finance.py` + `GET /api/finance` (siempre detrás de login): entra (MRR, el mismo cálculo de `/api/accounts`) / sale (costos) / margen del mes, más historial para tendencia. Las **categorías** de costo son política (`config.FINANCE_COST_CATEGORIES`: vapi, elevenlabs, supabase, dominio, vps, anthropic, otros); las **cifras reales** viven solo en `finance.json` (local, gitignorado, mismo trato que `crm.json` — se anota a mano, en CLP). Sin archivo, responde cifras de ejemplo con `source: "mock"`. Plan y decisiones de alcance en `docs/finanzas-plan.md`. La pestaña del dashboard es la parte pendiente (sección DASHBOARD).

## Modelo de agencia (multi-tenant)

Login único de agencia (un dueño); los clientes son cuentas internas. Cada cliente tiene su ICP guardado y su config de marketing por separado (cuenta Meta, presupuesto, zonas — foco Chile, default Santiago RM). Ver [[09 - Otros]].

## Valor por cierre

`AVG_DEAL_VALUE_CLP = 1.000.000` (CLP) alimenta el [[04 - CRM y Pipeline de Ventas|forecast]] de pipeline esperado.

> [!note]
> Política de costo cero: posponer **toda** integración de pago hasta poder pagarla; perfeccionar lo gratis primero. Ver [[06 - Roadmap]].
