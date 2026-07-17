# Finanzas de la agencia — audit y propuesta de alcance

> Sección FINANZAS · 2026-07-16 · **Solo plan, nada construido.** Diego elige una
> opción de la parte 3 antes de escribir código.

## 1. Qué datos financieros YA existen en el código

Hay que separar dos planos que hoy conviven en el código:

- **Finanzas de la AGENCIA** — cuánto entra y cuánto sale de ZeroAI. De esto solo
  existe el lado "entra" (MRR); el lado "sale" (costos) no existe en ningún lado.
- **Finanzas DEL CLIENTE** — pipeline proyectado, gasto de ads, cotizaciones a sus
  leads. Es plata del cliente, no de la agencia; útil como contexto pero no debe
  mezclarse en un tablero financiero de la agencia.

### Lado "entra" (agencia)

| Qué | Dónde | Detalle |
|---|---|---|
| Catálogo de precios por tier | `zero/config.py:55-84` | `TIERS`: STARTER $50.000 · GROWTH $200.000 · SCALE $500.000 · ENTERPRISE `None` (negociado), CLP/mes. Es **política** — no se toca ni se mueve. |
| MRR real | `api.py:147-159` | `GET /api/accounts` suma `price_clp` del tier de cada cuenta activa del CRM → `mrr_clp`. **Único lugar del código que ya calcula "cuánto entra".** Detrás de login. |
| Cambio de plan | `api.py:166-173` | `POST /api/accounts/{client}/plan` — mueve un cliente de tier (afecta el MRR de la foto siguiente). |
| Catálogo público filtrado | `api.py:134-144` | `GET /api/public/plans` expone solo `segment/price_clp/leads_per_mo` (`_PLANS`, `api.py:134-135`). Es la **referencia de qué es seguro sin login**: precios de catálogo sí, MRR/cuentas jamás. |

Limitación clave del MRR actual: es una **foto del momento** (cuentas activas ×
precio de lista). No registra desde cuándo factura cada cliente, precios
negociados distintos de la lista (ENTERPRISE = `None` suma $0), ni si el mes se
**cobró** de verdad (facturado ≠ cobrado).

### Plano "del cliente" (existe, pero no es finanzas de la agencia)

| Qué | Dónde | Detalle |
|---|---|---|
| Pipeline proyectado | `api.py:184` + `zero/config.py:168-173,210-229` | `pipeline_clp = won × AVG_DEAL_VALUE_CLP` ($1.000.000) y `project_funnel` → `expected_pipeline_clp`. Valor del embudo **del cliente**. |
| Gasto de ads | `api.py:251-264` + `zero/metaads.py:30` | `spent_clp`, `cpl_clp`, benchmark `good_cpl_clp: 6000` (`CHILE`). Presupuesto de Meta **del cliente** (mock hoy; insights reales pendientes de pago). |
| Cotizaciones | `zero/quotes.py` + `zero/config.py:179` + `api.py:749-759` | Presupuestos deterministas con `IVA_RATE = 0.19`. Plata entre el cliente y **sus** leads. |

## 2. Qué falta

### Costos de la agencia — hoy: nada en código, solo menciones en docs

| Costo | Estado | De dónde saldría el número |
|---|---|---|
| Vapi (llamadas) | **Activo, pagando** (`docs/roadmap.md:91-92`) | Por uso/minuto. Manual desde su dashboard, o su API (los objetos de llamada traen `cost`) — automatizable después si vale la pena. |
| Supabase | Activo, **plan gratis $0** (`docs/roadmap.md:70`) | Hoy $0. Si sube de plan: manual (no hay API de billing estable que valga el esfuerzo). |
| ElevenLabs (voz Francisca) | En curso de conectarse (`docs/roadmap.md:230-232`) | Por caracteres. Manual, o `GET /v1/user/subscription` de su API (uso del plan). |
| Dominio | Mencionado solo en el prompt/docs | Manual, 1 cifra/año. |
| VPS (si se migra del PC Ubuntu) | Hipotético (`docs/futuro-escalabilidad.md`) | Manual cuando exista. |
| Anthropic API | No activo (motor local gratis desde 2026-07-06) | Manual si se activa; la consola de Anthropic muestra el gasto. |

Nota: el presupuesto de **Meta Ads** no va aquí — es plata del cliente (o hay que
decidir explícitamente quién la paga; hoy el código la trata como del cliente).

**Recomendación de fuente: manual primero.** Son ~4 cifras que cambian una vez al
mes; conectar APIs de facturación es exactamente el tipo de frente nuevo que la
disciplina de alcance prohíbe abrir sin necesidad real. Las APIs (Vapi,
ElevenLabs) quedan anotadas como mejora futura, no como requisito.

### Otras piezas que no existen

- **Moneda**: los costos vienen en **USD** (Vapi, ElevenLabs) y los ingresos en
  **CLP**. Hace falta un tipo de cambio — manual al registrar el costo (simple) o
  una API gratis tipo mindicador.cl (después, si molesta).
- **Historial**: sin registro mes a mes no hay tendencia de MRR ni de margen —
  solo fotos.
- **Cobranza**: no existe "este cliente pagó julio". Es la diferencia entre MRR
  teórico y caja real.
- **Precio negociado**: ENTERPRISE (`price_clp: None`) necesita un precio por
  cuenta para no sumar $0 al MRR.

## 3. Opciones de alcance (Diego elige)

### Opción A — Registro manual sin código (doc/planilla local)

Un archivo local **fuera de git** (o gitignorado, como `state.json`/`crm.json`)
donde Diego anota cada mes: MRR (lo da `GET /api/accounts`), costos, margen.

- **Pros:** cero código, cero mantención, cero riesgo de filtrar cifras. Se puede
  empezar hoy. Perfecto para validar si el hábito de registrar siquiera se sostiene.
- **Contras:** todo manual (incluso copiar el MRR que el sistema ya sabe); sin
  visibilidad en el dashboard; nada impide que se desactualice en silencio.

### Opción B — Módulo backend mínimo, mock-first (`zero/finance.py` + endpoint con login)

- `zero/finance.py`: lee costos de un **archivo local gitignorado**
  (`finance.json`, mismo trato que `crm.json`) y los cruza con el MRR que
  `/api/accounts` ya calcula → resumen mensual (entra / sale / margen).
- `GET /api/finance` **detrás de login** (nunca en `_OPEN_PATHS`); mock con cifras
  de ejemplo cuando no hay `finance.json`, fiel al contrato.
- Las **categorías** de costo (qué rubros existen) van en `config.py` como
  política; las **cifras reales** solo en el archivo local.

- **Pros:** sigue la arquitectura del repo (política/mecanismo, mock-first, datos
  locales); una sola fuente de verdad; el MRR deja de copiarse a mano; deja la
  mesa servida para el dashboard sin comprometerse a él.
- **Contras:** código nuevo que mantener (regla 4: cada feature es un pasivo);
  ingresar costos sigue siendo manual (editar un JSON); sin UI, se consulta por
  `curl` o similar.

### Opción C — Opción B + pestaña "Finanzas" en el dashboard

Lo mismo que B, más una vista en `frontend/`: MRR por cliente, costos del mes,
margen, y tendencia cuando haya historial. **La parte de UI sería un prompt
aparte para DASHBOARD** — esta sección no toca `frontend/`.

- **Pros:** visibilidad real de un vistazo, que es lo que "llevar las finanzas"
  termina significando; usa las primitivas visuales que el dashboard ya tiene.
- **Contras:** dos secciones y dos prompts coordinados; más superficie que
  mantener; sin historial acumulado el gráfico de tendencia nace vacío (la
  pestaña rinde más si B lleva 1-2 meses guardando datos).

### Sugerencia (no decisión)

**B ahora, C en un mes.** A no aprovecha que el MRR ya está calculado; C completo
de una vez abre dos frentes a la vez. B es chico (~1 módulo + 1 endpoint + tests),
respeta todas las reglas del repo, y convierte a C en un paso corto cuando ya
haya datos que mostrar.

## Restricciones para cuando se construya (cualquier opción)

1. **Cifras reales nunca en git**: ni costos ni MRR real hardcodeados en archivos
   versionados ni en docs que se suban. Datos reales solo en archivos locales
   gitignorados (patrón `state.json`/`crm.json`: si están corruptos, avisar, no
   sobrescribir).
2. **Nada financiero real sin login**: `/api/public/plans` sigue siendo la única
   puerta pública y solo con precios de catálogo. Cualquier endpoint de finanzas
   queda fuera de `_OPEN_PATHS` (`api.py:64`).
3. **Mock-first**: el modo mock del módulo usa cifras de ejemplo con la misma
   forma de datos que las reales.
4. **`zero/config.py::TIERS` no se toca ni se mueve** — es política de CORE.
