import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { Terminal, AlertTriangle, Play, Pencil, Trash2, Plus, CheckCircle2, XCircle, Repeat } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { useDismiss } from '../hooks/useDismiss'
import { useApp } from '../App'
import { Card, Button, Input, Skeleton, pageState, Eyebrow, SectionTitle } from '../components/ui'
import { rise, fade, surface, staggerDense, overlay, dialog } from '../lib/motion'

/* Panel exclusivo del admin: crear/editar/correr/borrar funciones — código
   Python a medida que corre AISLADO (Docker, zero/sandbox.py) contra leads
   reales del cliente activo (lookup_scope.client_id = cliente global del
   dashboard, no un selector propio — así nunca se corre "a ciegas" contra un
   cliente distinto del que se está mirando). Una función puede quedar
   solo-manual, o disparándose sola cada N minutos (schedule.interval_minutes,
   el scheduler vive en zero/functions.py) — en ambos casos "Correr ahora"
   siempre está disponible para forzar una corrida. */

const emptyForm = { id: null, name: '', code: '', stage: '', enabled: true, scheduleEnabled: false, intervalMinutes: '' }

const timeAgo = (iso) => {
  if (!iso) return 'nunca'
  const ms = Date.now() - new Date(iso).getTime()
  const min = Math.round(ms / 60000)
  if (min < 1) return 'recién'
  if (min < 60) return `hace ${min} min`
  const h = Math.round(min / 60)
  if (h < 24) return `hace ${h} h`
  return `hace ${Math.round(h / 24)} d`
}

// Mismo criterio que timeAgo pero hacia adelante — para "próxima corrida".
const timeUntil = (iso) => {
  if (!iso) return null
  const ms = new Date(iso).getTime() - Date.now()
  if (ms <= 0) return 'en instantes'
  const min = Math.round(ms / 60000)
  if (min < 1) return 'en instantes'
  if (min < 60) return `en ${min} min`
  const h = Math.round(min / 60)
  if (h < 24) return `en ${h} h`
  return `en ${Math.round(h / 24)} d`
}

export default function Funciones() {
  const { client } = useApp()
  const qc = useQueryClient()
  const [form, setForm] = useState(null) // null = form cerrado; objeto = abierto (nuevo o edición)
  // useCallback para que el efecto de Escape no se re-suscriba en cada render.
  const closeForm = useCallback(() => setForm(null), [])
  useDismiss(!!form, closeForm)
  const [runningId, setRunningId] = useState(null)

  const { data: functions, isLoading, error, refetch } = useQuery({ queryKey: ['functions'], queryFn: api.functions })

  const save = useMutation({
    mutationFn: (body) => api.saveFunction(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['functions'] })
      toast.success('Función guardada')
      setForm(null)
    },
    onError: (e) => toast.error('No se pudo guardar: ' + e.message),
  })

  const del = useMutation({
    mutationFn: (id) => api.deleteFunction(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['functions'] }); toast.success('Función eliminada') },
    onError: (e) => toast.error('No se pudo eliminar: ' + e.message),
  })

  const run = useMutation({
    mutationFn: (id) => api.runFunction(id),
    onMutate: (id) => setRunningId(id),
    onSettled: () => setRunningId(null),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ['functions'] })
      const ok = d?.run?.error == null
      if (ok) toast.success('Corrida OK')
      else toast.error('Corrida con error: ' + d.run.error)
    },
    onError: (e) => toast.error('No se pudo correr: ' + e.message),
  })

  const gate = pageState({
    isLoading, error, onRetry: refetch,
    skeleton: <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-20 w-full" />)}</div>,
  })

  const openNew = () => setForm({ ...emptyForm })
  const openEdit = (fn) => setForm({
    id: fn.id, name: fn.name, code: fn.code, stage: fn.lookup_scope?.stage || '', enabled: fn.enabled,
    scheduleEnabled: !!fn.schedule,
    intervalMinutes: fn.schedule?.interval_minutes != null ? String(fn.schedule.interval_minutes) : '',
  })

  const submit = () => {
    if (!form.name.trim()) return toast.error('Ponle un nombre a la función')
    if (!form.code.trim()) return toast.error('La función necesita código')
    let schedule = null
    if (form.scheduleEnabled) {
      const n = parseInt(form.intervalMinutes, 10)
      if (!Number.isInteger(n) || n <= 0 || String(n) !== form.intervalMinutes.trim()) {
        return toast.error('El intervalo del disparo automático debe ser un número entero mayor a 0')
      }
      schedule = { interval_minutes: n }
    }
    save.mutate({
      id: form.id || undefined,
      name: form.name.trim(),
      code: form.code,
      lookup_scope: { client_id: client, stage: form.stage.trim() || null },
      enabled: form.enabled,
      schedule,
    })
  }

  return (
    <motion.div className="space-y-5 max-w-3xl" initial="hidden" animate="show" variants={rise}>
      <motion.div className="flex items-center justify-between gap-3 flex-wrap" variants={fade}>
        <div className="flex items-center gap-2">
          <Terminal size={18} className="text-gold-deep" />
          <SectionTitle>Funciones</SectionTitle>
        </div>
        <Button variant="primary" onClick={openNew}><Plus size={15} /> Nueva función</Button>
      </motion.div>

      <motion.div variants={fade}>
        <Card className="p-4 flex items-start gap-3 bg-amber-50/60 border-amber-200">
        <AlertTriangle size={17} className="text-amber-700 shrink-0 mt-0.5" />
        <div className="text-sm text-amber-800">
          Cada función corre código Python real, aislado en un contenedor Docker, contra los{' '}
          <b>leads reales</b> del cliente activo (<b>{client}</b>) — solo ve campos curados
          (empresa, nombre, rol, email, teléfono, etapa, score), nunca credenciales ni datos de
          otros clientes. Puedes dejarla disparándose sola cada N minutos (disparo automático),
          o correrla solo cuando aprietas "Correr ahora" — ambas conviven, "Correr ahora" siempre
          funciona aunque esté en automático.
        </div>
        </Card>
      </motion.div>

      {gate || (
        <motion.div className="space-y-2" variants={staggerDense()} initial="hidden" animate="show">
          {(!functions || functions.length === 0) && (
            <motion.div className="py-16 text-center text-zinc-400" variants={fade}>Sin funciones todavía — crea la primera.</motion.div>
          )}
          {functions?.map((fn) => (
            <motion.div key={fn.id} variants={surface}>
              <Card className="p-4 space-y-2">
                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-zinc-800 truncate">{fn.name}</span>
                      {!fn.enabled && (
                        <span className="text-[11px] font-medium text-zinc-400 bg-zinc-100 rounded-full px-2 py-0.5">deshabilitada</span>
                      )}
                      {fn.schedule && (
                        <span className="text-[11px] font-semibold text-gold-deep bg-champagne/40 rounded-full px-2 py-0.5 inline-flex items-center gap-1 shrink-0">
                          <Repeat size={11} /> automática · cada {fn.schedule.interval_minutes} min
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-zinc-400 mt-0.5">
                      {fn.lookup_scope?.client_id}{fn.lookup_scope?.stage ? ` · etapa ${fn.lookup_scope.stage}` : ' · todas las etapas'}
                      {' · creada por '}{fn.created_by || '—'}
                      {fn.schedule && fn.next_run && ` · próxima corrida ${timeUntil(fn.next_run)}`}
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <Button variant="soft" onClick={() => run.mutate(fn.id)} disabled={!fn.enabled || runningId === fn.id} title="Correr ahora">
                      <Play size={14} /> {runningId === fn.id ? 'Corriendo…' : 'Correr ahora'}
                    </Button>
                    <Button variant="ghost" onClick={() => openEdit(fn)} title="Editar"><Pencil size={15} /></Button>
                    <Button variant="ghost" onClick={() => { if (confirm(`¿Eliminar "${fn.name}"?`)) del.mutate(fn.id) }} title="Eliminar">
                      <Trash2 size={15} className="text-rose-500" />
                    </Button>
                  </div>
                </div>
                {fn.last_run && (
                  <div className={'text-xs rounded-lg px-3 py-2 flex items-start gap-2 ' + (fn.last_run.ok ? 'bg-emerald-50 text-emerald-800' : 'bg-rose-50 text-rose-700')}>
                    {fn.last_run.ok ? <CheckCircle2 size={14} className="shrink-0 mt-0.5" /> : <XCircle size={14} className="shrink-0 mt-0.5" />}
                    <div className="min-w-0">
                      <span className="font-medium">{timeAgo(fn.last_run.at)}: </span>
                      <span className="break-words">{fn.last_run.result_summary}</span>
                    </div>
                  </div>
                )}
              </Card>
            </motion.div>
          ))}
        </motion.div>
      )}

      <AnimatePresence>
        {form && (
          <motion.div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4" {...overlay} onClick={closeForm}>
            <motion.div className="bg-white dark:bg-[#1D2016] rounded-2xl max-w-lg w-full p-6 space-y-4 max-h-[90vh] overflow-y-auto" {...dialog} onClick={(e) => e.stopPropagation()}>
            <div className="text-lg font-bold">{form.id ? 'Editar función' : 'Nueva función'}</div>

            {/* El texto va envuelto en <span>: si queda suelto dentro del flex,
                cada trozo y el <b> se vuelven ítems flex separados y el `gap-2`
                los espacia — el nombre del cliente y el punto final terminaban
                flotando lejos de la frase. */}
            <div className="text-xs text-amber-700 bg-amber-50 rounded-lg px-3 py-2 flex items-start gap-2">
              <AlertTriangle size={14} className="shrink-0 mt-0.5" />
              <span>
                Se guarda tal cual — no se valida hasta que la corras. Va a ejecutarse aislada,
                pero contra leads reales de <b>{client}</b>.
              </span>
            </div>

            <div>
              <label className="block text-xs text-zinc-500 mb-1">Nombre</label>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Detectar leads sin respuesta 7 días" />
            </div>
            <div>
              <label className="block text-xs text-zinc-500 mb-1">Etapa (opcional — vacío = todas)</label>
              <Input value={form.stage} onChange={(e) => setForm({ ...form, stage: e.target.value })} placeholder="contacted" />
            </div>
            <div>
              <label className="block text-xs text-zinc-500 mb-1">Código (Python)</label>
              <textarea
                value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value })}
                rows={12}
                spellCheck={false}
                placeholder={'# ctx trae {"leads": [...], "client_id": "..."}\nresult = [l for l in ctx["leads"] if l["score"] >= 80]'}
                className="w-full border border-zinc-200 rounded-xl px-3 py-2 text-sm font-mono outline-none transition focus:ring-4 focus:ring-champagne/40 focus:border-gold/60 bg-zinc-50"
              />
            </div>
            <label className="flex items-center gap-2 text-sm text-zinc-600 cursor-pointer">
              <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} className="accent-gold" />
              Habilitada
            </label>

            <div>
              <label className="flex items-center gap-2 text-sm text-zinc-600 cursor-pointer">
                <input type="checkbox" checked={form.scheduleEnabled}
                  onChange={(e) => setForm({ ...form, scheduleEnabled: e.target.checked })} className="accent-gold" />
                Disparo automático
              </label>
              {form.scheduleEnabled && (
                <div className="mt-2 flex items-center gap-2">
                  <span className="text-xs text-zinc-500">cada</span>
                  <Input type="number" min="1" step="1" value={form.intervalMinutes}
                    onChange={(e) => setForm({ ...form, intervalMinutes: e.target.value })}
                    placeholder="30" className="w-24" />
                  <span className="text-xs text-zinc-500">minutos</span>
                </div>
              )}
            </div>

            <div className="flex justify-end gap-2 pt-1">
              <Button variant="ghost" onClick={closeForm}>Cancelar</Button>
              <Button variant="accent" onClick={submit} disabled={save.isPending}>Guardar</Button>
            </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
