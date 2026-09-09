import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { AlertTriangle, Check, X } from 'lucide-react'
import { api } from '../lib/api'
import { Card, Eyebrow, SectionTitle, Spinner } from '../components/ui'
import { fade, surface, stagger, prefersReducedMotion } from '../lib/motion'

/* Lo que está pasando ahora mismo con una corrida del pipeline.
 *
 * Antes, "Buscar leads" abría una request que quedaba colgada los minutos que de verdad
 * tarda una corrida real, con la pantalla quieta: no había forma de saber si el modelo
 * estaba trabajando o si algo se había caído. Lo único que llegaba era un toast al final.
 *
 * Dos cosas condicionan el diseño de esto, y ninguna es obvia:
 *
 * 1. **El avance va por lotes, no a goteo.** `descubriendo` y `calificando` son UNA
 *    llamada al modelo cada una, así que sus empresas aparecen todas juntas de golpe.
 *    Solo `validando` y `escribiendo` avanzan de a una. Por eso la cascada se aplica al
 *    grupo que entra (stagger sobre los nuevos), en vez de animar celda por celda como
 *    si llegaran de a una: eso último se vería como un tartamudeo.
 *
 * 2. **El orden ya viene resuelto del backend** (avance, luego recencia) y no se toca
 *    acá. Reordenar en cliente haría que la lista bailara en cada tick, que es
 *    justamente lo que vuelve ilegible un panel que se refresca cada segundo.
 */

/* El vocabulario de etapas viaja en la respuesta (`etapas`), así que la barra se pinta
   con ESE array. Este mapa es solo el color de cada una: si el backend agrega una etapa
   mañana, cae en el `default` y se ve gris, pero no rompe nada. */
const TONO = {
  descubierta: { punto: '#8C929B', texto: 'text-pewter' },
  calificada: { punto: '#C9A45C', texto: 'text-gold-deep' },
  aprobada: { punto: '#C9A45C', texto: 'text-gold-deep' },
  lista: { punto: '#16a34a', texto: 'text-emerald-600' },
  descartada: { punto: '#e11d48', texto: 'text-rose-600' },
}
const tono = (etapa) => TONO[etapa] || { punto: '#8C929B', texto: 'text-pewter' }

/* Cuánto puede quedarse una empresa en la misma etapa antes de que valga la pena
   señalarla. Es una decisión de presentación, no una regla de negocio: no cambia nada
   del pipeline, solo dónde mira el ojo cuando algo se está demorando. */
const SEGUNDOS_ESTANCADA = 25

const transcurrido = (desde, ahora) => Math.max(0, Math.round(ahora - (desde || ahora)))

/* Pregunta por el avance mientras la corrida esté viva.
 *
 * Usa setTimeout encadenado y no setInterval: si un tick tarda más de un segundo,
 * setInterval encolaría peticiones encima de la anterior y terminarías con varias en
 * vuelo contra el mismo endpoint. Acá el siguiente tick se agenda cuando el anterior ya
 * volvió.
 *
 * Se detiene solo en tres casos, sin excepciones: la corrida dejó de estar "corriendo",
 * la petición falló (incluido el 404 de una corrida que el anillo ya olvidó), o el
 * componente se desmontó. El `vivo` de la ref es lo que garantiza el tercero: sin él,
 * un timeout ya agendado dispararía una petición después de que el usuario se fue de la
 * página. */
function useProgreso(runId) {
  const [datos, setDatos] = useState(null)
  const [fallo, setFallo] = useState(null)

  useEffect(() => {
    if (!runId) { setDatos(null); setFallo(null); return }
    let vivo = true
    let timer = null

    const tick = async () => {
      try {
        const d = await api.pipelineProgress(runId)
        if (!vivo) return
        setDatos(d)
        if (d.estado === 'corriendo') timer = setTimeout(tick, 1000)
      } catch (e) {
        if (!vivo) return
        setFallo(e.message || 'no se pudo leer el avance')
      }
    }
    tick()

    return () => { vivo = false; if (timer) clearTimeout(timer) }
  }, [runId])

  return { datos, fallo }
}

/* Reloj propio, solo para que los "hace 12 s" avancen entre respuesta y respuesta.
   Se apaga cuando la corrida termina: un temporizador corriendo sobre datos que ya no
   cambian es puro gasto de batería. */
function useAhora(activo) {
  const [ahora, setAhora] = useState(() => Date.now() / 1000)
  useEffect(() => {
    if (!activo) return
    const id = setInterval(() => setAhora(Date.now() / 1000), 1000)
    return () => clearInterval(id)
  }, [activo])
  return ahora
}

function BarraDeFases({ etapas, fase, conteos }) {
  /* `fase` (descubriendo/calificando/…) y `etapas` (descubierta/calificada/…) son dos
     vocabularios distintos: uno describe qué está haciendo el pipeline, el otro en qué
     estado quedó cada empresa. Se muestran los dos porque responden preguntas
     diferentes: "¿en qué anda?" y "¿cómo va el reparto?". */
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {etapas.map((etapa) => {
        const n = conteos[etapa] || 0
        const t = tono(etapa)
        return (
          <span key={etapa}
            className={'inline-flex items-center gap-1.5 text-xs rounded-full px-2.5 py-1 border ' +
              (n ? 'border-zinc-200 bg-zinc-50' : 'border-transparent opacity-45')}>
            <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: t.punto }} />
            <span className="capitalize text-zinc-600">{etapa}</span>
            <b className="tabular-nums text-zinc-800">{n}</b>
          </span>
        )
      })}
      {fase && (
        <span className="text-[11px] uppercase tracking-wide text-zinc-400 ml-1">
          {fase}
        </span>
      )}
    </div>
  )
}

function Celda({ lead, ahora }) {
  const t = tono(lead.etapa)
  const secs = transcurrido(lead.desde, ahora)
  const estancada = secs >= SEGUNDOS_ESTANCADA && lead.etapa !== 'lista' && lead.etapa !== 'descartada'
  const descartada = lead.etapa === 'descartada'

  return (
    <motion.div
      layout={!prefersReducedMotion()}
      variants={surface}
      className={'rounded-xl border p-3 min-w-0 ' +
        (descartada ? 'border-zinc-200 bg-zinc-50/60 opacity-75'
          : estancada ? 'border-champagne bg-champagne/10'
            : 'border-zinc-200 bg-white dark:bg-zinc-50')}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="text-sm font-semibold text-zinc-800 truncate min-w-0">{lead.empresa}</div>
        {lead.score != null && (
          <span className="text-xs font-extrabold tabular-nums shrink-0" style={{ color: t.punto }}>
            {lead.score}
          </span>
        )}
      </div>

      <div className="flex items-center gap-1.5 mt-1.5">
        <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: t.punto }} />
        <span className={'text-xs font-medium capitalize ' + t.texto}>{lead.etapa}</span>
        {lead.canal && <span className="text-[11px] text-zinc-400">· {lead.canal}</span>}
        <span className="text-[11px] text-zinc-400 ml-auto tabular-nums shrink-0">{secs}s</span>
      </div>

      {/* El motivo del descarte viene listo del backend ("score 56 < 60"). Sin esto hay
          que abrir el CRM para entender por qué una empresa se cayó, que es exactamente
          la pregunta que uno se hace mirando esta pantalla. */}
      {descartada && lead.motivo && (
        <div className="text-[11px] text-zinc-500 mt-1.5 flex items-start gap-1">
          <X size={11} className="text-rose-500 shrink-0 mt-0.5" />
          <span className="min-w-0">{lead.motivo}</span>
        </div>
      )}

      {estancada && (
        <div className="text-[11px] text-gold-deep mt-1.5">lleva {secs}s en esta etapa</div>
      )}
    </motion.div>
  )
}

/* `onEmpresas` avisa hacia arriba qué empresas está mostrando este panel, para que la
   tabla del CRM las esconda mientras tanto y el mismo lead no quede visible dos veces.
   `onFin` se dispara una sola vez cuando la corrida deja de correr. */
export default function PipelineRun({ runId, onEmpresas, onFin }) {
  const { datos, fallo } = useProgreso(runId)
  const corriendo = datos?.estado === 'corriendo'
  const ahora = useAhora(corriendo)
  const avisado = useRef(null)

  const leads = datos?.leads || []
  const etapas = datos?.etapas || []

  useEffect(() => {
    onEmpresas?.(corriendo ? leads.map((l) => l.empresa) : [])
  }, [corriendo, leads.map((l) => l.empresa).join('|')])   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!datos || datos.estado === 'corriendo') return
    if (avisado.current === datos.run) return
    avisado.current = datos.run
    onFin?.(datos)
  }, [datos?.estado, datos?.run])   // eslint-disable-line react-hooks/exhaustive-deps

  if (!runId) return null

  if (fallo) {
    return (
      <motion.div variants={fade} initial="hidden" animate="show">
        <Card className="p-4 flex items-start gap-2.5 border-amber-200 bg-amber-50/60">
          <AlertTriangle size={16} className="text-amber-700 shrink-0 mt-0.5" />
          <div className="text-sm text-amber-800 min-w-0">
            No se pudo seguir el avance de esta corrida: {fallo}
            <div className="text-xs text-amber-700/80 mt-0.5">
              Los leads que alcanzó a dejar listos igual están en la tabla de abajo.
            </div>
          </div>
        </Card>
      </motion.div>
    )
  }

  if (!datos) {
    return (
      <motion.div variants={fade} initial="hidden" animate="show">
        <Card className="p-4 flex items-center gap-2.5 text-sm text-zinc-500">
          <Spinner /> Enganchando con la corrida…
        </Card>
      </motion.div>
    )
  }

  const conteos = leads.reduce((acc, l) => ({ ...acc, [l.etapa]: (acc[l.etapa] || 0) + 1 }), {})
  const errado = datos.estado === 'error'

  return (
    <motion.div variants={surface} initial="hidden" animate="show">
      <Card className={'p-5 ' + (errado ? 'border-rose-200' : corriendo ? 'border-champagne' : '')}>
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0">
            <Eyebrow>{corriendo ? 'Corriendo ahora' : errado ? 'Corrida con error' : 'Corrida terminada'}</Eyebrow>
            <SectionTitle className="mt-0.5 truncate">{datos.consulta || 'Búsqueda de leads'}</SectionTitle>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {corriendo && <Spinner />}
            {!corriendo && !errado && <Check size={16} className="text-emerald-600" />}
            <span className="text-xs text-zinc-500 tabular-nums">
              {Math.round(datos.segundos || 0)}s · {datos.encontradas || 0} encontradas
            </span>
          </div>
        </div>

        {/* Si la corrida reventó, el error va arriba de todo: es lo único que importa. */}
        {errado && datos.error && (
          <div className="mt-3 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-3 py-2">
            {datos.error}
          </div>
        )}

        {etapas.length > 0 && (
          <div className="mt-3">
            <BarraDeFases etapas={etapas} fase={corriendo ? datos.fase : null} conteos={conteos} />
          </div>
        )}

        {/* Las celdas por empresa existen SOLO mientras la corrida está viva. En cuanto
            termina, el pipeline ya escribió esos leads en el CRM y la tabla de abajo los
            muestra con su ficha completa: dejar las celdas puestas haría que la misma
            empresa se viera dos veces en la pantalla, una arriba y otra abajo. Lo que
            queda es el resumen —qué se buscó y cómo quedó el reparto—, que la tabla no
            dice y sigue siendo útil.

            La cascada se aplica al grupo: `descubriendo` y `calificando` sueltan todas
            sus empresas de una sola vez, así que lo que entra es un lote, no una fila. */}
        <AnimatePresence initial={false}>
          {corriendo && (
            <motion.div
              key="celdas"
              className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2.5 mt-4"
              variants={stagger()} initial="hidden" animate="show" exit={{ opacity: 0 }}
            >
              {leads.map((l) => <Celda key={l.empresa} lead={l} ahora={ahora} />)}
            </motion.div>
          )}
        </AnimatePresence>

        {corriendo && leads.length === 0 && !errado && (
          <div className="text-sm text-zinc-400 mt-4">
            Todavía no hay empresas — el primer lote aparece cuando el modelo termine de descubrir.
          </div>
        )}

        {!corriendo && !errado && (
          <div className="text-sm text-zinc-500 mt-3">
            {datos.listas || 0} listas para contactar · {datos.descartadas || 0} descartadas.
            Ya están en la tabla de abajo con su ficha completa.
          </div>
        )}
      </Card>
    </motion.div>
  )
}
