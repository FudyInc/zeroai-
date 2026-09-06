import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { History, RotateCcw, Check } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { Button, Eyebrow, Spinner } from './ui'
import { fade, surface, stagger, overlay, dialog } from '../lib/motion'

/* El historial de la ficha: qué versión está vigente, qué hubo antes, y volver atrás.
 *
 * Hasta ahora guardar la ficha sobrescribía sin dejar rastro. Eso hacía que ajustarla
 * fuera una apuesta: si el cambio empeoraba las respuestas, no había forma de recuperar
 * el texto anterior salvo reescribirlo de memoria.
 *
 * Restaurar NO borra el intento que se está dejando: el backend guarda la restauración
 * como una versión nueva. Saber qué se probó y no funcionó es justamente lo que evita
 * volver a probarlo la semana que viene.
 */

const cuando = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  return d.toLocaleString('es-CL', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export default function KnowledgeHistory({ client }) {
  const qc = useQueryClient()
  const [abierto, setAbierto] = useState(false)
  const [confirmar, setConfirmar] = useState(null)   // la versión que se va a restaurar
  const [restaurando, setRestaurando] = useState(false)

  const versionsQ = useQuery({
    queryKey: ['knowledge-versions', client],
    queryFn: () => api.knowledgeVersions(client),
    enabled: !!client && abierto,
  })

  const versiones = versionsQ.data?.versions || []
  const actual = versionsQ.data?.current

  const restaurar = async (version) => {
    setRestaurando(true)
    try {
      await api.rollbackKnowledge(client, version)
      /* La ficha cambió: quien la muestre tiene que volver a pedirla, o el textarea
         seguiría enseñando el texto viejo como si nada hubiera pasado. */
      qc.invalidateQueries({ queryKey: ['knowledge', client] })
      qc.invalidateQueries({ queryKey: ['knowledge-versions', client] })
      setConfirmar(null)
      toast.success(`Ficha restaurada desde la v${version}`, {
        description: 'Quedó como versión nueva: el texto que tenías antes no se borró.',
      })
    } catch (e) {
      toast.error('No se pudo restaurar: ' + e.message)
    } finally { setRestaurando(false) }
  }

  if (!client) return null

  return (
    <div className="mt-3 border-t border-zinc-100 pt-3">
      <button
        onClick={() => setAbierto((v) => !v)}
        className="text-xs text-zinc-500 hover:text-zinc-700 inline-flex items-center gap-1.5 transition-colors"
      >
        <History size={13} />
        {abierto ? 'Ocultar historial' : 'Ver historial de la ficha'}
        {actual != null && <span className="text-zinc-400">· vigente v{actual}</span>}
      </button>

      <AnimatePresence initial={false}>
        {abierto && (
          <motion.div key="hist" variants={fade} initial="hidden" animate="show" exit={{ opacity: 0 }} className="mt-3">
            {versionsQ.isLoading ? (
              <div className="text-xs text-zinc-400 flex items-center gap-2"><Spinner /> cargando historial…</div>
            ) : versionsQ.isError ? (
              <div className="text-xs text-rose-600">
                No se pudo leer el historial.{' '}
                <button className="underline" onClick={() => versionsQ.refetch()}>Reintentar</button>
              </div>
            ) : versiones.length === 0 ? (
              <div className="text-xs text-zinc-400">
                Todavía no hay versiones guardadas — aparecen al guardar la ficha.
              </div>
            ) : (
              <motion.div className="space-y-1.5" variants={stagger()} initial="hidden" animate="show">
                {versiones.map((v) => (
                  <motion.div key={v.version} variants={surface}
                    className={'rounded-xl border p-2.5 flex items-start gap-3 ' +
                      (v.vigente ? 'border-champagne bg-champagne/10' : 'border-zinc-200')}>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-semibold text-zinc-700">v{v.version}</span>
                        {v.vigente && (
                          <span className="text-[10px] font-semibold text-gold-deep bg-champagne/40 rounded-full px-2 py-0.5 inline-flex items-center gap-1">
                            <Check size={10} /> vigente
                          </span>
                        )}
                        <span className="text-[11px] text-zinc-400 tabular-nums">
                          {cuando(v.guardada)} · {(v.chars || 0).toLocaleString('es-CL')} caracteres
                        </span>
                        {v.motivo && <span className="text-[11px] text-zinc-400">· {v.motivo}</span>}
                      </div>
                      {v.preview && (
                        <div className="text-[11px] text-zinc-500 mt-1 line-clamp-2 break-words">{v.preview}…</div>
                      )}
                    </div>
                    {!v.vigente && (
                      <Button variant="ghost" className="shrink-0 text-xs"
                        onClick={() => setConfirmar(v)} disabled={restaurando}>
                        <RotateCcw size={13} /> Volver a esta
                      </Button>
                    )}
                  </motion.div>
                ))}
              </motion.div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Restaurar cambia lo que el agente sabe y afecta a los leads que escriban después,
          así que se confirma antes: es una acción de una sola tecla con efecto invisible. */}
      <AnimatePresence>
        {confirmar && (
          <motion.div
            className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4"
            {...overlay} onClick={() => !restaurando && setConfirmar(null)}
          >
            <motion.div className="bg-white dark:bg-zinc-50 rounded-2xl max-w-md w-full p-6 space-y-3"
              {...dialog} onClick={(e) => e.stopPropagation()}>
              <div className="text-lg font-bold">¿Volver a la versión {confirmar.version}?</div>
              <p className="text-sm text-zinc-500">
                El agente pasará a responder con ese texto. La ficha de ahora no se pierde:
                la restauración queda como una versión nueva, así que puedes deshacerla.
              </p>
              {confirmar.preview && (
                <div className="text-xs text-zinc-500 bg-zinc-50 border border-zinc-200 rounded-xl p-3 max-h-32 overflow-auto whitespace-pre-wrap">
                  {confirmar.preview}…
                </div>
              )}
              <div className="flex justify-end gap-2 pt-1">
                <Button variant="ghost" onClick={() => setConfirmar(null)} disabled={restaurando}>Cancelar</Button>
                <Button variant="accent" onClick={() => restaurar(confirmar.version)} disabled={restaurando}>
                  {restaurando ? 'Restaurando…' : 'Sí, restaurar'}
                </Button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
