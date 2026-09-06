import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { FlaskConical, Play, Plus, Trash2, X, Check, Square } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { Card, Button, Input, Eyebrow, SectionTitle, Spinner, Skeleton } from './ui'
import { fade, surface, stagger } from '../lib/motion'

/* El banco de preguntas de una empresa, y la tanda que las corre contra la ficha actual.
 *
 * El problema que resuelve: cada ensayo en el chat de prueba era desechable. Se tocaba la
 * ficha para arreglar una respuesta y se rompían otras tres sin que nadie se enterara,
 * porque nadie volvía a preguntar lo mismo de antes. Acá las preguntas quedan guardadas y
 * se repiten enteras después de cada cambio.
 *
 * Dos cosas deliberadas:
 *
 * 1. **No hay puntaje ni semáforo.** `respuesta_esperada` es una referencia para que una
 *    persona compare, no un assert: nada acá decide si la respuesta está bien. Un juez
 *    automático se descartó a propósito, y poner un ✓/✗ sería colarlo por la puerta de
 *    atrás con peor criterio.
 *
 * 2. **La tanda va de a una pregunta.** Con el motor local a ~40 tok/s, veinte preguntas
 *    son minutos: mandarlas juntas sería una sola request colgada que además expira. Cada
 *    respuesta se pinta en cuanto llega, y se puede cortar a media tanda.
 */

/* La corrida anterior se guarda en memoria del componente, no en el servidor: no hay
   endpoint para persistir resultados y tampoco hace falta: la comparación que importa es
   "antes y después de este cambio que acabo de hacer", que ocurre en una sola sesión. Si
   recargas, pierdes el antes — a cambio de no inventar un formato de persistencia que
   CORE no pidió. */
const vacia = () => ({ id: '', pregunta: '', respuesta_esperada: '', nota: '' })

function EditorDeCasos({ casos, onChange, disabled }) {
  const set = (i, campo, valor) => {
    const copia = casos.slice()
    copia[i] = { ...copia[i], [campo]: valor }
    onChange(copia)
  }
  return (
    <motion.div className="space-y-2.5" variants={stagger()} initial="hidden" animate="show">
      {casos.map((c, i) => (
        <motion.div key={c.id || i} variants={surface}
          className="rounded-xl border border-zinc-200 p-3 space-y-2">
          <div className="flex items-start gap-2">
            <span className="text-[11px] font-semibold text-zinc-400 tabular-nums mt-2.5 w-5 shrink-0">
              {i + 1}
            </span>
            <div className="flex-1 min-w-0 space-y-2">
              <Input
                value={c.pregunta} disabled={disabled}
                onChange={(e) => set(i, 'pregunta', e.target.value)}
                placeholder="La pregunta que haría un cliente. Ej: ¿hacen despacho a regiones?"
                className="w-full"
              />
              <textarea
                value={c.respuesta_esperada} disabled={disabled}
                onChange={(e) => set(i, 'respuesta_esperada', e.target.value)}
                rows={2}
                placeholder="Qué debería contestar (opcional) — es una referencia para comparar a ojo, no se evalúa sola."
                className="w-full border border-zinc-200 rounded-xl px-3 py-2 text-sm outline-none transition focus:ring-4 focus:ring-champagne/40 focus:border-gold/60 placeholder:text-zinc-400 resize-y"
              />
              {(c.nota || !disabled) && (
                <Input
                  value={c.nota} disabled={disabled}
                  onChange={(e) => set(i, 'nota', e.target.value)}
                  placeholder="Nota para ti (opcional)"
                  className="w-full text-xs"
                />
              )}
            </div>
            <button
              onClick={() => onChange(casos.filter((_, j) => j !== i))}
              disabled={disabled}
              title="Quitar esta pregunta"
              className="text-zinc-400 hover:text-rose-500 transition-colors mt-2.5 shrink-0 disabled:opacity-40"
            >
              <Trash2 size={15} />
            </button>
          </div>
        </motion.div>
      ))}
    </motion.div>
  )
}

/* Una fila de la comparación. Tres columnas cuando hay corrida anterior: qué se esperaba,
   qué contestó antes, qué contesta ahora. El ojo va a la diferencia entre las dos
   últimas; la esperada es la vara. */
function Comparacion({ caso, antes, ahora, corriendo }) {
  return (
    <motion.div variants={surface} className="rounded-xl border border-zinc-200 p-3.5">
      <div className="text-sm font-semibold text-zinc-800">{caso.pregunta}</div>
      {caso.nota && <div className="text-[11px] text-zinc-400 mt-0.5">{caso.nota}</div>}

      <div className={'grid gap-3 mt-3 ' + (antes ? 'md:grid-cols-3' : 'md:grid-cols-2')}>
        <div className="min-w-0">
          <Eyebrow>Esperada</Eyebrow>
          <div className="text-[13px] text-zinc-500 mt-1 whitespace-pre-wrap break-words">
            {caso.respuesta_esperada || <span className="text-zinc-300">— sin referencia —</span>}
          </div>
        </div>

        {antes && (
          <div className="min-w-0">
            <Eyebrow>Antes {antes.version != null && `· ficha v${antes.version}`}</Eyebrow>
            <div className="text-[13px] text-zinc-500 mt-1 whitespace-pre-wrap break-words">
              {antes.error ? <span className="text-rose-500">{antes.error}</span> : antes.reply}
            </div>
          </div>
        )}

        <div className="min-w-0">
          <Eyebrow>{antes ? 'Ahora' : 'Respuesta'} {ahora?.version != null && `· ficha v${ahora.version}`}</Eyebrow>
          <div className="text-[13px] text-zinc-700 mt-1 whitespace-pre-wrap break-words">
            {ahora?.error
              ? <span className="text-rose-500">{ahora.error}</span>
              : ahora?.reply
                ? ahora.reply
                : corriendo
                  ? <span className="text-zinc-400 inline-flex items-center gap-1.5"><Spinner /> esperando…</span>
                  : <span className="text-zinc-300">— sin correr —</span>}
          </div>
        </div>
      </div>
    </motion.div>
  )
}

export default function CasesLab({ client, vendorId }) {
  const qc = useQueryClient()
  const casesQ = useQuery({
    queryKey: ['cases', client], queryFn: () => api.cases(client), enabled: !!client,
  })
  const versionsQ = useQuery({
    queryKey: ['knowledge-versions', client], queryFn: () => api.knowledgeVersions(client), enabled: !!client,
  })

  const [casos, setCasos] = useState([])
  const [cargadoPara, setCargadoPara] = useState(null)
  const [resultados, setResultados] = useState({})     // id -> {reply, error, version}
  const [anteriores, setAnteriores] = useState(null)   // la tanda previa, para comparar
  const [progreso, setProgreso] = useState(null)       // {hecho, total}
  const cancelar = useRef(false)

  useEffect(() => {
    if (casesQ.data && cargadoPara !== client) {
      setCasos(casesQ.data)
      setCargadoPara(client)
      setResultados({}); setAnteriores(null); setProgreso(null)
    }
  }, [casesQ.data, client, cargadoPara])

  const versionActual = versionsQ.data?.current ?? null
  const sucio = JSON.stringify(casos) !== JSON.stringify(casesQ.data || [])
  const corriendo = progreso !== null

  const guardar = async () => {
    try {
      await api.setCases(client, casos)
      qc.invalidateQueries({ queryKey: ['cases', client] })
      setCargadoPara(null)
      toast.success('Banco de preguntas guardado')
    } catch (e) { toast.error('No se pudo guardar: ' + e.message) }
  }

  /* La tanda. Va de a una y espera cada respuesta antes de pedir la siguiente: el motor
     local responde a ~40 tok/s y veinte preguntas en paralelo lo saturan sin acelerar
     nada. `cancelar` es una ref y no estado porque el bucle ya está corriendo cuando se
     aprieta el botón — un estado no se vería desde dentro de esta closure. */
  const correr = async () => {
    const listos = casos.filter((c) => c.pregunta.trim())
    if (!listos.length) { toast.error('Agrega al menos una pregunta'); return }

    if (Object.keys(resultados).length) setAnteriores({ resultados, version: versionActual })
    setResultados({})
    cancelar.current = false
    setProgreso({ hecho: 0, total: listos.length })

    for (let i = 0; i < listos.length; i++) {
      if (cancelar.current) break
      const caso = listos[i]
      try {
        const body = { client, message: caso.pregunta, history: [] }
        if (vendorId) body.vendor_id = vendorId
        const { reply } = await api.simulateAgent(body)
        if (cancelar.current) break
        setResultados((r) => ({ ...r, [caso.id || caso.pregunta]: { reply, version: versionActual } }))
      } catch (e) {
        if (cancelar.current) break
        setResultados((r) => ({ ...r, [caso.id || caso.pregunta]: { error: e.message, version: versionActual } }))
      }
      setProgreso({ hecho: i + 1, total: listos.length })
    }

    /* Se limpia siempre, se haya cortado o no: dejar el progreso puesto es lo que deja la
       pantalla con un spinner que no termina nunca. */
    setProgreso(null)
    if (cancelar.current) toast('Tanda cortada', { description: 'Lo que alcanzó a responder queda en pantalla.' })
  }

  if (!client) return null

  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <FlaskConical size={16} className="text-gold-deep" />
            <SectionTitle>Banco de preguntas</SectionTitle>
          </div>
          <div className="text-xs text-zinc-400 mt-1 max-w-xl">
            Las mismas preguntas, repetidas después de cada cambio de ficha. Así se ve qué
            arreglaste y qué rompiste sin tener que acordarte de lo que preguntaste la vez pasada.
            {versionActual != null && <> Ficha vigente: <b className="text-zinc-500">v{versionActual}</b>.</>}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {sucio && (
            <Button variant="soft" onClick={guardar} disabled={corriendo}>Guardar banco</Button>
          )}
          {corriendo ? (
            <Button variant="soft" onClick={() => { cancelar.current = true }}>
              <Square size={13} /> Cortar
            </Button>
          ) : (
            <Button variant="accent" onClick={correr} disabled={!casos.length}>
              <Play size={14} /> Correr la tanda
            </Button>
          )}
        </div>
      </div>

      {corriendo && (
        <motion.div variants={fade} initial="hidden" animate="show" className="mt-3">
          <div className="flex items-center gap-2 text-sm text-zinc-600">
            <Spinner />
            caso {Math.min(progreso.hecho + 1, progreso.total)} de {progreso.total}
          </div>
          <div className="w-full h-1.5 bg-zinc-100 rounded-full mt-2 overflow-hidden">
            <div className="h-full bg-gold-deep rounded-full transition-all"
              style={{ width: `${(progreso.hecho / progreso.total) * 100}%` }} />
          </div>
        </motion.div>
      )}

      {casesQ.isLoading ? (
        <div className="space-y-2 mt-4">{[0, 1].map((i) => <Skeleton key={i} className="h-20 w-full" />)}</div>
      ) : (
        <div className="mt-4 space-y-4">
          {/* Con resultados en pantalla, la comparación desplaza al editor: lo que se está
              mirando es qué contestó, no qué preguntar. El editor vuelve al limpiar. */}
          {Object.keys(resultados).length || corriendo ? (
            <motion.div className="space-y-2.5" variants={stagger()} initial="hidden" animate="show">
              <AnimatePresence initial={false}>
                {casos.filter((c) => c.pregunta.trim()).map((c) => (
                  <Comparacion
                    key={c.id || c.pregunta}
                    caso={c}
                    antes={anteriores?.resultados?.[c.id || c.pregunta]}
                    ahora={resultados[c.id || c.pregunta]}
                    corriendo={corriendo}
                  />
                ))}
              </AnimatePresence>
            </motion.div>
          ) : (
            <>
              <EditorDeCasos casos={casos} onChange={setCasos} disabled={corriendo} />
              {!casos.length && (
                <div className="text-sm text-zinc-400 py-6 text-center">
                  Sin preguntas todavía. Agrega las que un cliente hace siempre.
                </div>
              )}
            </>
          )}

          <div className="flex items-center gap-2">
            <Button variant="soft" disabled={corriendo}
              onClick={() => { setCasos([...casos, { ...vacia(), id: Math.random().toString(36).slice(2, 14) }]); setResultados({}) }}>
              <Plus size={14} /> Agregar pregunta
            </Button>
            {Object.keys(resultados).length > 0 && !corriendo && (
              <Button variant="ghost" onClick={() => { setResultados({}); setAnteriores(null) }}>
                <X size={14} /> Volver al editor
              </Button>
            )}
            {anteriores && (
              <span className="text-[11px] text-zinc-400">
                comparando contra la tanda anterior{anteriores.version != null && ` (ficha v${anteriores.version})`}
              </span>
            )}
          </div>
        </div>
      )}
    </Card>
  )
}
