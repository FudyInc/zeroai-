import { motion } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import { LANE, leadRoute } from '../lib/util'
import { rise, fade, stagger, meterFill } from '../lib/motion'

/* Por dónde va un lead en su recorrido, de un vistazo.
 *
 * DIBUJA, no decide: todo lo que muestra sale de `leadRoute()` en lib/util.js, que a su
 * vez solo lee el registro que ya manda el CRM. Acá no hay ninguna regla de negocio.
 *
 * Dos tamaños:
 *   <LeadRoute lead={r} />           completo — etiquetas, fechas y la salida
 *   <LeadRoute lead={r} compact />   mini-barra de 4px para la tarjeta del Kanban
 *
 * Sobre el movimiento: el relleno usa `meterFill`, el único elemento del lenguaje que
 * puede pasar de ~380 ms porque ahí el recorrido ES el dato. `initial` solo corre al
 * montar; cuando el lead cambia de etapa, framer interpola del ancho viejo al nuevo. Un
 * re-render de react-query con el mismo porcentaje no anima nada — no hay replay.
 */

/* Mitad de una columna: el riel va de centro a centro de los puntos extremos, no de
   borde a borde, para que el 0% y el 100% caigan justo bajo el primer y último punto. */
const HALF = `${100 / (LANE.length * 2)}%`

/* El visto bueno pendiente cae ENTRE calificado (paso 1) y contactado (paso 2). */
const APPROVAL_AT = `${(1.5 * 100) / (LANE.length - 1)}%`

export default function LeadRoute({ lead, compact = false }) {
  const route = leadRoute(lead)
  return compact ? <CompactRoute route={route} /> : <FullRoute route={route} />
}

/* --- completo, para el detalle del lead ------------------------------------------- */

function FullRoute({ route }) {
  const nav = useNavigate()
  const { steps, pct, color, exit, pendingApproval, days } = route

  return (
    <motion.div className="mt-4" variants={rise} initial="hidden" animate="show">
      <div className="flex items-baseline gap-2 mb-3">
        <div className="text-xs uppercase tracking-wide text-zinc-400">Recorrido</div>
        {days != null && (
          <div className="text-xs text-zinc-400">
            {days === 0 ? 'hoy' : `hace ${days} ${days === 1 ? 'día' : 'días'}`}
          </div>
        )}
      </div>

      <div className="relative h-3">
        {/* riel: la parte recorrida se pinta del color de donde está hoy el lead */}
        <div className="absolute top-[5px] h-[2px]" style={{ left: HALF, right: HALF }}>
          <div className="absolute inset-0 rounded-full bg-zinc-200 dark:bg-zinc-300/60" />
          <motion.div className="absolute left-0 top-0 h-full rounded-full"
            style={{ background: color }} {...meterFill(pct)} />
          {pendingApproval && (
            <button type="button" onClick={() => nav('/aprobar')}
              title="Esperando tu visto bueno"
              className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-2.5 h-2.5 rounded-full
                         bg-gold ring-2 ring-white dark:ring-zinc-50 animate-pulse cursor-pointer"
              style={{ left: APPROVAL_AT }} />
          )}
        </div>

        {/* los puntos */}
        <motion.div className="relative grid" variants={stagger()}
          style={{ gridTemplateColumns: `repeat(${LANE.length}, minmax(0, 1fr))` }}>
          {steps.map((s) => (
            <motion.div key={s.stage} variants={fade} className="flex items-center justify-center h-3">
              <span
                className={'rounded-full ring-2 ring-white dark:ring-zinc-50 ' +
                  (s.current ? 'w-3 h-3' : 'w-2.5 h-2.5') +
                  (s.done ? '' : ' border-2 border-zinc-300 dark:border-zinc-400')}
                style={{
                  background: s.done ? s.color : 'transparent',
                  /* halo del punto actual: el mismo color de la etapa al 20% */
                  boxShadow: s.current ? `0 0 0 4px ${s.color}33` : undefined,
                }}
              />
            </motion.div>
          ))}
        </motion.div>
      </div>

      {/* etiquetas y fechas, una columna por paso */}
      <div className="grid mt-2" style={{ gridTemplateColumns: `repeat(${LANE.length}, minmax(0, 1fr))` }}>
        {steps.map((s) => (
          <div key={s.stage} className="px-0.5 text-center">
            <div className={'text-[10px] leading-tight ' +
              (s.current ? 'font-semibold text-zinc-700' : s.done ? 'text-zinc-500' : 'text-zinc-300')}>
              {s.label}
            </div>
            {/* Sin fecha no se escribe nada: `new` no deja evento y `advance` puede
                saltarse pasos. Un guion de relleno se leería como dato faltante. */}
            {s.at && <div className="text-[10px] text-zinc-400 tabular-nums mt-0.5">{s.at}</div>}
          </div>
        ))}
      </div>

      {pendingApproval && (
        <button type="button" onClick={() => nav('/aprobar')}
          className="mt-2 text-[11px] text-gold-deep hover:underline">
          Esperando tu visto bueno →
        </button>
      )}

      {/* La salida es un desvío del camino, no un paso más adelante: cuelga del último
          punto que el lead alcanzó de verdad. */}
      {exit && (
        <div className="relative mt-1 h-8" style={{ marginLeft: HALF, marginRight: HALF }}>
          {/* La línea siempre cae bajo el punto alcanzado; el chip se ancla al mismo
              sitio pero se pega al borde en los extremos. Centrado a ciegas, un lead
              `won → lost` (salida al 100%) sacaba medio chip fuera del modal. */}
          <div className="absolute top-0 flex flex-col"
            style={{
              left: `${pct}%`,
              alignItems: pct >= 90 ? 'flex-end' : pct <= 10 ? 'flex-start' : 'center',
              transform: `translateX(${pct >= 90 ? '-100%' : pct <= 10 ? '0' : '-50%'})`,
            }}>
            <span className="w-px h-3" style={{ background: exit.color }} />
            <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold whitespace-nowrap"
              style={{ background: exit.color + '1a', color: exit.color }}>
              {exit.label}{exit.at ? ` · ${exit.at}` : ''}
            </span>
          </div>
        </div>
      )}
    </motion.div>
  )
}

/* --- compacto, para la tarjeta del Kanban ----------------------------------------- */

/* 4px de alto y sin texto: en una columna del tablero el carril es una señal periférica,
   no algo que se lea. Sin manejadores de puntero — la tarjeta que lo contiene es
   `draggable` y cualquier handler acá le robaría el arrastre. */
function CompactRoute({ route }) {
  const { steps, pct, color, exit } = route
  const actual = exit ? exit.label : (steps.find((s) => s.current)?.label ?? '')
  return (
    <div className="relative h-1 mt-2.5" role="img" title={actual}
      aria-label={actual ? `Recorrido: ${actual}` : 'Recorrido del lead'}>
      <div className="absolute inset-0 rounded-full bg-zinc-200 dark:bg-zinc-300/60" />
      <motion.div className="absolute inset-y-0 left-0 rounded-full"
        style={{ background: color }} {...meterFill(pct)} />
      <div className="absolute inset-0 grid" style={{ gridTemplateColumns: `repeat(${LANE.length}, minmax(0, 1fr))` }}>
        {steps.map((s) => (
          <div key={s.stage} className="flex justify-center">
            <span className={'w-1 h-1 rounded-full ' + (s.done ? '' : 'bg-zinc-300 dark:bg-zinc-400')}
              style={s.done ? { background: s.color } : undefined} />
          </div>
        ))}
      </div>
    </div>
  )
}
