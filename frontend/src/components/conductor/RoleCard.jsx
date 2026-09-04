import { Play, Square, Loader2, Bot, Hammer, Bug, Palette, FileText, Search, Terminal } from 'lucide-react'
import { Card, Button, Select } from '../ui'
import { cn } from '../../lib/util'

/* Identidad de cada rol por ICONO, no por emoji: un emoji se dibuja con la
   fuente del sistema operativo, así que el mismo panel se ve distinto en cada
   máquina (en un Chromium sin fuente de emoji salen como cuadros vacíos) y
   rompe con el resto del dashboard, que ya usa lucide en todo el sidebar. */
const ROLE_ICON = {
  agents: Bot, worker: Hammer, debug: Bug,
  design: Palette, prompts: FileText, consultas: Search,
}

/* Casi monocromo a propósito: solo los dos estados que piden atención (viva /
   caída) llevan color, el resto se lee en pewter como cualquier texto
   secundario. Seis píldoras de colores en una misma vista serían justo el
   arcoíris genérico que la dirección visual descarta. */
const STATUS = {
  running: { label: 'Corriendo', dot: 'bg-emerald-600' },
  starting: { label: 'Iniciando', dot: 'bg-zinc-400' },
  exited: { label: 'Terminada', dot: 'bg-zinc-300' },
  killed: { label: 'Detenida', dot: 'bg-zinc-300' },
  crashed: { label: 'Se cayó', dot: 'bg-rose-700' },
}
const ENDED = new Set(['exited', 'killed', 'crashed'])

/* Una fila por rol: qué es, qué zona toca, con qué modelo y en qué estado.
   El rol define QUÉ se toca; el modelo, cuánto piensa — por eso el selector
   vive acá, junto al botón de iniciar, y no escondido en la sesión. */
export default function RoleCard({ role, session, busy, models, model, onModelChange, onStart, onOpen, onStop }) {
  const Icon = ROLE_ICON[role.id] || Terminal
  const state = session ? (STATUS[session.status] || STATUS.running) : null
  const canStart = !session || ENDED.has(session.status)
  const live = session && !ENDED.has(session.status)

  /* Con el motor local no hay herramientas, así que la "zona de escritura" del
     rol sería una promesa falsa: esa terminal no escribe nada. Se dice lo que
     de verdad puede hacer. */
  const noTools = live
    ? session.tools === false
    : models.find((m) => m.id === model)?.tools === false
  const zone = noTools ? 'sin herramientas — solo conversa' : role.write_zone_hint

  return (
    <Card className="p-4 flex items-center gap-4">
      <div className="w-10 h-10 rounded-xl border border-champagne/50 dark:border-zinc-700/40 grid place-items-center shrink-0 text-pewter">
        <Icon size={17} strokeWidth={1.75} />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2.5">
          <span className="font-display text-sm font-semibold tracking-tight text-zinc-800">{role.label}</span>
          {state && (
            <span className="inline-flex items-center gap-1.5 text-[11px] text-pewter">
              <span className={cn('w-1.5 h-1.5 rounded-full', state.dot)} />
              {state.label}
            </span>
          )}
        </div>
        <div className="text-xs text-pewter mt-0.5 truncate">
          <span className={cn(noTools && 'text-gold-deep')}>{zone}</span>
          {live && session.model && <> · {session.model}</>}
        </div>
        {session?.started_by && !ENDED.has(session.status) && (
          <div className="text-[11px] text-pewter/80 mt-0.5 truncate">
            iniciada por {session.started_by.username || session.started_by.email || '—'}
          </div>
        )}
      </div>

      <div className="flex items-center gap-2 shrink-0">
        {canStart ? (
          <>
            <Select value={model} onChange={(e) => onModelChange(e.target.value)}
              className="text-xs py-1.5 w-28" aria-label={`Modelo para ${role.label}`}>
              {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </Select>
            <Button variant="primary" onClick={onStart} disabled={busy}>
              {busy ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />} Iniciar
            </Button>
          </>
        ) : (
          <>
            <Button variant="soft" onClick={onOpen}>Abrir</Button>
            <Button variant="ghost" onClick={onStop} title="Detener sesión">
              <Square size={14} />
            </Button>
          </>
        )}
      </div>
    </Card>
  )
}
