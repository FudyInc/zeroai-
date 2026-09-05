import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { Cpu, ArrowRight, Activity, AlertTriangle } from 'lucide-react'
import { api } from '../lib/api'
import { Card, Badge, Skeleton, SectionTitle } from '../components/ui'
import { Segmented } from '../components/Segmented'
import { rise, fade, surface, stagger, staggerDense, page, hoverLift } from '../lib/motion'

const AGENTS = [
  ['PROSPECTOR', 'descubre + enriquece'],
  ['QUALIFIER', 'califica vs ICP (0–100)'],
  ['OUTREACH', 'primer toque por canal'],
  ['TRACKER', 'follow-up: nudge→value→bye'],
  ['ANALYST', 'forecast (propone tasas)'],
  ['CONCIERGE', 'responde dudas + agenda', true],
]

const LAYERS = [
  ['Backends (LLM)', 'Mock · Local (Ollama) · Anthropic', 'intercambiable'],
  ['Canales (Outbox)', 'Mock · Email (SMTP) · WhatsApp', 'envía / recibe'],
  ['Datos', 'CRM (Supabase) · Memoria (ICP)', 'durable'],
]

const FLOW = ['discover', 'qualify', 'validate', 'outreach', 'follow-up', 'responde', 'forecast']

const TABS = [
  { value: 'Árbol', label: 'Árbol' },
  { value: 'Flujo', label: 'Flujo del pipeline' },
  { value: 'En vivo', label: 'En vivo' },
]

export default function Arquitectura() {
  const [tab, setTab] = useState('Árbol')
  return (
    <motion.div className="space-y-6" initial="hidden" animate="show" variants={rise}>
      <motion.div variants={fade}>
        <Segmented variant="dark" options={TABS} value={tab} onChange={setTab} />
      </motion.div>
      {/* Cambiar de pestaña acá es un cambio de vista completo, así que usa la misma
          variante que un cambio de página: sale hacia arriba, entra desde abajo. */}
      <AnimatePresence mode="wait">
        <motion.div key={tab} {...page}>
          {tab === 'Árbol' ? <TreeView /> : tab === 'Flujo' ? <FlowView /> : <LiveView />}
        </motion.div>
      </AnimatePresence>
    </motion.div>
  )
}

function TreeView() {
  return (
    <motion.div variants={stagger()} initial="hidden" animate="show" className="space-y-7">
      {/* ZERO */}
      <div className="flex justify-center">
        <motion.div variants={surface}>
          <div className="rounded-2xl px-7 py-4 bg-brand-surface text-white text-center shadow-lg shadow-black/10">
            <div className="flex items-center gap-2 justify-center font-display font-extrabold tracking-tight"><Cpu size={18} /> ZERO — orquestador</div>
            <div className="text-[11px] text-champagne/90 mt-0.5">el cerebro · lógica Python (no LLM) · reparte · gate · entrega</div>
          </div>
        </motion.div>
      </div>

      <Branch label="6 agentes — mismo contrato JSON · mock ⇄ real">
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {AGENTS.map(([n, d, isNew]) => (
            <motion.div key={n} variants={surface} {...hoverLift}
              className={'rounded-xl p-3 bg-white dark:bg-zinc-50 border text-center cursor-default ' + (isNew ? 'border-gold/60 ring-1 ring-champagne' : 'border-zinc-200')}>
              <div className={'text-[13px] font-display font-extrabold tracking-tight ' + (isNew ? 'text-gold-deep' : 'text-brand')}>{n}</div>
              <div className="text-[10.5px] text-zinc-500 mt-1 leading-snug">{d}</div>
              {isNew && <div className="text-[9px] font-bold text-gold-deep mt-1 tracking-wide">NUEVO</div>}
            </motion.div>
          ))}
        </div>
      </Branch>

      <Branch label="3 pilares de soporte — intercambiables, no tocan el cerebro">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {LAYERS.map(([n, d, tag]) => (
            <motion.div key={n} variants={surface} {...hoverLift}
              className="rounded-xl p-4 bg-white dark:bg-zinc-50 border border-zinc-200">
              <div className="text-[13px] font-display font-extrabold tracking-tight text-brand">{n}</div>
              <div className="text-[11px] text-zinc-500 mt-1">{d}</div>
              <div className="text-[9px] font-bold text-zinc-400 mt-2 uppercase tracking-wide">{tag}</div>
            </motion.div>
          ))}
        </div>
      </Branch>

      <motion.div variants={fade} className="text-center text-xs text-zinc-400">
        Superficies: CLI · API (FastAPI) · Dashboard React
      </motion.div>
    </motion.div>
  )
}

function Branch({ label, children }) {
  return (
    <div className="relative">
      <div className="flex justify-center mb-3">
        <div className="h-5 w-px bg-zinc-200" />
      </div>
      <div className="text-center text-[11px] font-semibold uppercase tracking-wide text-zinc-400 mb-3">{label}</div>
      {children}
    </div>
  )
}

function FlowView() {
  return (
    <Card className="p-8">
      <motion.div variants={stagger()} initial="hidden" animate="show"
        className="flex flex-wrap items-center justify-center gap-2">
        {FLOW.map((step, i) => (
          <motion.div key={step} variants={surface} className="flex items-center gap-2">
            <div className="rounded-full px-4 py-2 text-sm font-semibold bg-champagne/30 text-brand border border-champagne">
              {step}
            </div>
            {i < FLOW.length - 1 && <ArrowRight size={16} className="text-zinc-300" />}
          </motion.div>
        ))}
      </motion.div>
      <div className="text-center text-xs text-zinc-400 mt-6">
        Cada paso lo ejecuta un agente; todo queda registrado en el CRM.
      </div>
    </Card>
  )
}

/* "En vivo": qué agente corrió de verdad, con qué motor y cuánto tardó. Se alimenta de
   zero/telemetry.py, que registra CADA dispatch. Refresca solo cada 5s — el dato no es
   crítico y una consulta por segundo sería gastar batería del navegador en nada.

   Deliberadamente NO muestra el texto de los mensajes: por acá pasan conversaciones de
   leads reales y el registro guarda tamaños, no contenido. */
const STATUS_COLOR = { done: '#059669', partial: '#d97706', error: '#e11d48' }
const fmtMs = (ms) => (ms >= 1000 ? (ms / 1000).toFixed(1) + ' s' : Math.round(ms) + ' ms')
const hace = (ts) => {
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts))
  if (s < 60) return `hace ${s}s`
  if (s < 3600) return `hace ${Math.round(s / 60)} min`
  if (s < 86400) return `hace ${Math.round(s / 3600)} h`
  return `hace ${Math.round(s / 86400)} d`
}

function LiveView() {
  const q = useQuery({
    queryKey: ['agents-telemetry'],
    queryFn: () => api.agentsTelemetry(40),
    refetchInterval: 5000,
  })

  if (q.isLoading) return <Card className="p-6"><Skeleton className="h-40" /></Card>
  if (q.error) {
    return (
      <Card className="p-6 text-sm text-rose-600">
        No se pudo leer la actividad de los agentes.{' '}
        <button className="underline" onClick={() => q.refetch()}>Reintentar</button>
      </Card>
    )
  }

  const { agentes = [], recientes = [], eventos = 0, max_eventos: max = 0 } = q.data || {}

  if (!eventos) {
    return (
      <Card className="p-8 text-center">
        <Activity size={20} className="mx-auto text-zinc-300" />
        <div className="text-sm text-zinc-500 mt-2">
          Todavía no hay corridas registradas. Aparecen solas apenas un agente trabaje
          —una búsqueda de leads, un WhatsApp entrante, un seguimiento.
        </div>
      </Card>
    )
  }

  return (
    <motion.div className="space-y-5" variants={stagger()} initial="hidden" animate="show">
      <motion.div variants={surface}>
        <Card className="p-5">
        <SectionTitle className="flex items-center gap-2">
          <Activity size={16} /> Agentes — últimas {eventos} corridas
        </SectionTitle>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[11px] uppercase tracking-wide text-zinc-400 text-left">
                <th className="pb-2 font-semibold">Agente</th>
                <th className="pb-2 font-semibold">Motor</th>
                <th className="pb-2 font-semibold text-right">Corridas</th>
                <th className="pb-2 font-semibold text-right">Típico</th>
                <th className="pb-2 font-semibold text-right">Peor</th>
                <th className="pb-2 font-semibold text-right">Última</th>
              </tr>
            </thead>
            <motion.tbody variants={staggerDense()}>
              {agentes.map((a) => (
                <motion.tr key={a.agent} variants={fade} className="border-t border-zinc-100 dark:border-white/5">
                  <td className="py-2 font-display font-bold text-brand">
                    {a.agent}
                    {a.errores > 0 && (
                      <span className="ml-2 inline-flex items-center gap-1 text-[11px] text-rose-600">
                        <AlertTriangle size={11} /> {a.errores}
                      </span>
                    )}
                  </td>
                  <td className="py-2 text-zinc-500 text-xs">{a.engines.join(' · ') || '—'}</td>
                  <td className="py-2 text-right tabular-nums">{a.corridas}</td>
                  <td className="py-2 text-right tabular-nums">{fmtMs(a.ms_mediana)}</td>
                  <td className="py-2 text-right tabular-nums text-zinc-500">{fmtMs(a.ms_max)}</td>
                  <td className="py-2 text-right text-zinc-400 text-xs">{hace(a.ultimo)}</td>
                </motion.tr>
              ))}
            </motion.tbody>
          </table>
        </div>
        <div className="text-[11px] text-zinc-400 mt-3">
          "Típico" es la mediana, no el promedio: una sola corrida lenta (el modelo
          cargándose en memoria de la GPU) desvirtúa un promedio.
        </div>
        </Card>
      </motion.div>

      <motion.div variants={surface}>
        <Card className="p-5">
        <SectionTitle>Últimas corridas</SectionTitle>
        <motion.div className="mt-3 space-y-1.5 max-h-80 overflow-y-auto" variants={staggerDense()}>
          {recientes.map((e, i) => (
            <motion.div key={`${e.task_id}-${i}`} variants={fade}
              className="flex items-center gap-3 text-xs border-b border-zinc-50 dark:border-white/5 pb-1.5">
              <Badge color={STATUS_COLOR[e.status] || STATUS_COLOR.done}>{e.status}</Badge>
              <span className="font-semibold text-brand w-24 shrink-0">{e.agent}</span>
              <span className="text-zinc-400 w-20 shrink-0 text-right tabular-nums">{fmtMs(e.ms)}</span>
              <span className="text-zinc-400 truncate flex-1">{e.engine || '—'}</span>
              <span className="text-zinc-400 shrink-0">{e.client_id || '—'}</span>
              <span className="text-zinc-300 shrink-0">{hace(e.ts)}</span>
            </motion.div>
          ))}
        </motion.div>
        <div className="text-[11px] text-zinc-400 mt-3">
          Se guardan las últimas {max} corridas, sin el texto de los mensajes — por acá
          pasan conversaciones de leads reales.
        </div>
        </Card>
      </motion.div>
    </motion.div>
  )
}
