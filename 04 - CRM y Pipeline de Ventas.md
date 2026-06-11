# CRM y Pipeline de Ventas

Cada corrida del pipeline puebla un **CRM durable** (`crm.json`, o Supabase si está configurado): un registro por lead con su **etapa** en el funnel y su **historial** completo de interacciones. Código en `zero/crm.py` (y `zero/crm_supabase.py`).

## El gate — lead calificado

Un lead se **entrega** solo si se cumplen **todas** (ver `zero/config.py`):

- **contacto verificado** (email o teléfono)
- **ICP score ≥ 70** (`MIN_ICP_SCORE`)
- **no** está en la lista de exclusión del cliente
- tiene **company, role y channel** (`REQUIRED_FIELDS`)
- **no** fue contactado en los últimos **90 días** (`RECONTACT_BLACKOUT_DAYS`)

El [[02 - Arquitectura|QUALIFIER]] asigna el score; **ZERO** aplica el gate. Un candidato real suele llegar sin contacto verificado o con `role: "por verificar"` — justo lo que el gate filtra.

## Etapas del CRM

Ordenadas; el board las dibuja de izquierda a derecha (`CRM_STAGES`):

```
new → qualified / disqualified → contacted → nurturing → replied → meeting → won / lost
```

| Etapa | Significado |
|---|---|
| `new` | capturado, aún sin juzgar |
| `qualified` | pasó el gate |
| `disqualified` | falló el gate (se guarda para registro + analítica) |
| `contacted` | primer toque enviado |
| `nurturing` | en una secuencia de seguimiento activa |
| `replied` | el lead respondió |
| `meeting` | hay reunión agendada |
| `won` | cerrado ganado |
| `lost` | cerrado perdido / abandonado |

`CRM_OPEN_STAGES` = `new · qualified · contacted · nurturing · replied · meeting` (las "abiertas").

Las transiciones automáticas son **forward-only**: re-correr el pipeline **nunca** arrastra un lead cerrado hacia atrás. ZERO avanza las primeras (`new → qualified/disqualified → contacted → nurturing`); las últimas (`replied → won`) las mueve el humano a medida que aprende qué pasó.

## Cadencia de seguimiento (TRACKER)

Tras el primer toque (paso 0), [[02 - Arquitectura|TRACKER]] avanza al lead por estos pasos (`FOLLOWUP_STEPS`, `day` = offset desde el primer toque):

| Día | Tipo | Intención |
|---|---|---|
| 3 | `nudge` | recordatorio suave |
| 7 | `value` | suma una prueba / caso |
| 14 | `breakup` | último toque, deja la puerta abierta |

## Forecast (ANALYST)

La proyección del funnel es **determinista** (`project_funnel()` en `config.py`); [[02 - Arquitectura|ANALYST]] solo **propone** tasas. Defaults conservadores (`FORECAST_RATES`):

| Tasa | Default | Transición |
|---|---|---|
| `reply_rate` | 0.18 | contacted → replied |
| `meeting_rate` | 0.35 | replied → meeting |
| `win_rate` | 0.25 | meeting → won |

`AVG_DEAL_VALUE_CLP = 1.000.000` → pipeline esperado en CLP.

## Presentación / entrega

Solo dibujan o exportan — no deciden nada:

- **`zero/board.py`** — Kanban a color, columnas por etapa (`--action crm`).
- **`zero/export.py`** — entregable → CSV (lo que recibe el cliente).
- **Dashboard web** (`api.py` + `frontend/`) — lee el mismo CRM y lo muestra.

Comandos en [[07 - CLI y Comandos]].
