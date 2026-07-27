import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Cpu, ArrowRight } from 'lucide-react'
import { Card } from '../components/ui'
import { Segmented } from '../components/Segmented'

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

const TABS = [{ value: 'Árbol', label: 'Árbol' }, { value: 'Flujo', label: 'Flujo del pipeline' }]

export default function Arquitectura() {
  const [tab, setTab] = useState('Árbol')
  return (
    <div className="space-y-6">
      <Segmented variant="dark" options={TABS} value={tab} onChange={setTab} />
      <AnimatePresence mode="wait">
        <motion.div
          key={tab}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
        >
          {tab === 'Árbol' ? <TreeView /> : <FlowView />}
        </motion.div>
      </AnimatePresence>
    </div>
  )
}

const container = { hidden: {}, show: { transition: { staggerChildren: 0.06 } } }
const pop = {
  hidden: { opacity: 0, y: 14, scale: 0.97 },
  show: { opacity: 1, y: 0, scale: 1, transition: { type: 'spring', stiffness: 320, damping: 26 } },
}

function TreeView() {
  return (
    <motion.div variants={container} initial="hidden" animate="show" className="space-y-7">
      {/* ZERO */}
      <div className="flex justify-center">
        <motion.div variants={pop}>
          <div className="rounded-2xl px-7 py-4 bg-brand text-white text-center shadow-lg shadow-black/10">
            <div className="flex items-center gap-2 justify-center font-display font-extrabold tracking-tight"><Cpu size={18} /> ZERO — orquestador</div>
            <div className="text-[11px] text-champagne/90 mt-0.5">el cerebro · lógica Python (no LLM) · reparte · gate · entrega</div>
          </div>
        </motion.div>
      </div>

      <Branch label="6 agentes — mismo contrato JSON · mock ⇄ real">
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {AGENTS.map(([n, d, isNew]) => (
            <motion.div key={n} variants={pop} whileHover={{ y: -4 }}
              className={'rounded-xl p-3 bg-white dark:bg-[#1D2016] border text-center cursor-default ' + (isNew ? 'border-gold/60 ring-1 ring-champagne' : 'border-zinc-200')}>
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
            <motion.div key={n} variants={pop} whileHover={{ y: -4 }}
              className="rounded-xl p-4 bg-white dark:bg-[#1D2016] border border-zinc-200">
              <div className="text-[13px] font-display font-extrabold tracking-tight text-brand">{n}</div>
              <div className="text-[11px] text-zinc-500 mt-1">{d}</div>
              <div className="text-[9px] font-bold text-zinc-400 mt-2 uppercase tracking-wide">{tag}</div>
            </motion.div>
          ))}
        </div>
      </Branch>

      <motion.div variants={pop} className="text-center text-xs text-zinc-400">
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
      <motion.div variants={container} initial="hidden" animate="show"
        className="flex flex-wrap items-center justify-center gap-2">
        {FLOW.map((step, i) => (
          <motion.div key={step} variants={pop} className="flex items-center gap-2">
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
