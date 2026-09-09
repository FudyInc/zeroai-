import { clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs) {
  return twMerge(clsx(inputs))
}

export const STAGES = {
  new: { l: 'Nuevos', c: '#64748b' },
  qualified: { l: 'Calificados', c: '#0284c7' },
  disqualified: { l: 'Descartados', c: '#e11d48' },
  contacted: { l: 'Contactados', c: '#d97706' },
  nurturing: { l: 'En seguimiento', c: '#db2777' },
  replied: { l: 'Respondieron', c: '#2563eb' },
  meeting: { l: 'Reunión', c: '#059669' },
  won: { l: 'Ganados', c: '#16a34a' },
  lost: { l: 'Perdidos', c: '#94a3b8' },
}
export const ORDER = ['new', 'qualified', 'disqualified', 'contacted', 'nurturing', 'replied', 'meeting', 'won', 'lost']

export const scoreColor = (s) => (s == null ? '#94a3b8' : s >= 80 ? '#16a34a' : s >= 70 ? '#d97706' : '#dc2626')

const DAY_MS = 24 * 60 * 60 * 1000

// Cuenta leads que pasaron a "replied" en las últimas 24h, usando el historial
// del CRM (ya viene en /api/leads). Sin `channel`, cuenta todos los canales.
// null = sin datos todavía (sin cliente, cargando o error).
export function repliedRecently(leads, channel) {
  if (!leads) return null
  const cutoff = Date.now() - DAY_MS
  return leads.filter((r) => {
    if (channel && r.channel !== channel) return false
    if (r.stage !== 'replied') return false
    const ev = (r.history || []).slice().reverse()
      .find((h) => h.event === 'stage' && (h.detail || '').includes('replied'))
    return ev?.ts && new Date(ev.ts).getTime() >= cutoff
  }).length
}

/* --- El recorrido de un lead ------------------------------------------------------
 *
 * EL CARRIL SON 7 PASOS, NO LAS 9 ETAPAS DE `STAGES`.
 *
 * `disqualified` y `lost` no son pasos más adelante en el camino: son SALIDAS. La razón
 * vive en el núcleo, no acá — zero/crm.py::_ORDER le da a `disqualified` el mismo rango
 * que a `qualified`, y a `lost` el mismo que a `won`:
 *
 *     "new": 0, "qualified": 1, "disqualified": 1, "contacted": 2, ...
 *
 * O sea: un lead descartado NO está más avanzado que uno calificado. Dibujar las nueve
 * en fila haría que la pantalla afirmara un progreso que el CRM nunca dijo. `ORDER`
 * (arriba) sigue teniendo las nueve porque el Kanban necesita una columna por etapa,
 * incluidas las salidas; son dos preguntas distintas y por eso son dos listas distintas.
 */
export const LANE = ['new', 'qualified', 'contacted', 'nurturing', 'replied', 'meeting', 'won']

/* Los rangos del CRM impiden retrocesos automáticos; no prueban pasos recorridos. */
const EXITS = new Set(['disqualified', 'lost'])

/* Los dos extremos de un evento de etapa. `detail` tiene la forma "qualified →
   contacted", y set_stage puede agregarle un motivo entre paréntesis (zero/crm.py:119).
   Interesan AMBOS lados: el destino dice a dónde llegó, y el origen prueba dónde estuvo
   — un lead cuyo único evento es "contacted → disqualified" alcanzó "contactado", y
   leyendo solo destinos ese paso se perdía. */
function stageEdge(detail) {
  const [from, to] = String(detail || '').split('→')
  const limpio = (x) => (x ? x.replace(/\s*\(.*$/, '').trim() || null : null)
  return { from: limpio(from), to: to === undefined ? null : limpio(to) }
}

const shortDate = (ts) => {
  if (!ts) return null
  const d = new Date(ts)
  return Number.isNaN(d.getTime()) ? null : d.toLocaleDateString('es-CL', { day: 'numeric', month: 'short' })
}

/* Deriva el recorrido de un lead para dibujarlo. DERIVA, no decide: no hay ninguna
   regla de negocio nueva acá, solo lectura del registro que ya manda el CRM. */
export function leadRoute(lead) {
  const stage = lead?.stage
  /* `Array.isArray` y no `|| []`: si `history` viniera con otra forma, un `.filter`
     sobre algo que no es lista tira una excepción y deja el tablero entero en blanco. */
  const hist = Array.isArray(lead?.history) ? lead.history : []
  const events = hist.filter((h) => h && h.event === 'stage')

  /* Última vez que entró a esa etapa, no la primera: el recorrido no es monótono
     (set_stage es incondicional, así que arrastrar una tarjeta hacia atrás en el
     Kanban hace retroceder al lead de verdad). */
  const arrivedAt = (st) => {
    for (let i = events.length - 1; i >= 0; i--) {
      if (stageEdge(events[i].detail).to === st) return events[i].ts || null
    }
    return null
  }

  const exitStage = EXITS.has(stage) ? stage : null

  /* La posición la manda `lead.stage`, siempre — nunca se deduce del historial.
     Si el lead salió del camino, el carril llega hasta el paso más lejano que sí
     alcanzó según el historial
     (un lead contactado y después descartado llegó hasta "contactado"). */
  let reached
  if (exitStage) {
    reached = -1
    for (const ev of events) {
      const { from, to } = stageEdge(ev.detail)
      for (const st of [from, to]) {
        const i = LANE.indexOf(st)
        if (i > reached) reached = i
      }
    }
  } else {
    reached = LANE.indexOf(stage)      // -1 si la etapa es desconocida: carril apagado
  }

  const steps = LANE.map((st, i) => ({
    stage: st,
    label: STAGES[st].l,
    color: STAGES[st].c,
    done: i <= reached,
    current: !exitStage && i === reached,
    /* Un paso cumplido puede no tener evento: `new` nunca se registra (upsert crea
       el lead ya en esa etapa, zero/crm.py:84) y `advance` puede saltarse pasos.
       Se muestra cumplido y SIN fecha — interpolarla sería inventar el dato. */
    at: i <= reached ? shortDate(arrivedAt(st)) : null,
  }))

  const currentTs = arrivedAt(stage)
  const days = currentTs ? Math.floor((Date.now() - new Date(currentTs).getTime()) / DAY_MS) : null

  return {
    steps,
    reached,
    pct: reached > 0 ? (reached * 100) / (LANE.length - 1) : 0,
    color: (exitStage ? STAGES[exitStage] : STAGES[stage])?.c || '#94a3b8',
    exit: exitStage
      ? { label: STAGES[exitStage].l, color: STAGES[exitStage].c, at: shortDate(arrivedAt(exitStage)) }
      : null,
    /* El borrador esperando visto bueno es un SUB-ESTADO, no una etapa: vive entre
       "calificado" y "contactado" y no se agrega a STAGES/ORDER. Definición canónica
       en zero/crm.py::pending_outreach_count. */
    pendingApproval: lead?.outreach?.status === 'draft',
    /* Antigüedad en el punto actual. Sin evento que lleve a la etapa actual no se
       muestra: no hay de dónde sacarla. */
    days: days != null && days >= 0 ? days : null,
  }
}
