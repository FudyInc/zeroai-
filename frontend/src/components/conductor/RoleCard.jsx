import { Play, Square, Loader2 } from 'lucide-react'
import { Card, Button, Badge } from '../ui'

const STATUS_STYLE = {
  running: { label: 'Corriendo', color: '#16794f' },
  starting: { label: 'Iniciando…', color: '#a68a2e' },
  exited: { label: 'Terminada', color: '#71717a' },
  killed: { label: 'Detenida', color: '#71717a' },
  crashed: { label: 'Se cayó', color: '#dc2626' },
}
const ENDED = new Set(['exited', 'killed', 'crashed'])

/* Card por rol (molde: Equipo.jsx) — un vistazo a las 6 terminales del
   proyecto: emoji + zona de escritura + modelo + estado en vivo. `session`
   es la más reciente de ese rol, o null si nunca se lanzó. */
export default function RoleCard({ role, session, busy, onStart, onOpen, onStop }) {
  const style = session ? (STATUS_STYLE[session.status] || STATUS_STYLE.running) : null
  const canStart = !session || ENDED.has(session.status)

  return (
    <Card className="p-4 flex items-center gap-4">
      <div className="w-10 h-10 rounded-full bg-champagne/40 grid place-items-center shrink-0 text-lg">
        {role.emoji}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-zinc-800">{role.label}</span>
          {style && <Badge color={style.color}>{style.label}</Badge>}
        </div>
        <div className="text-xs text-zinc-400 mt-0.5 truncate">
          {role.write_zone_hint} · {role.model || 'opus (default)'}
        </div>
        {session?.started_by && !ENDED.has(session.status) && (
          <div className="text-[11px] text-zinc-400 mt-0.5 truncate">
            iniciada por {session.started_by.username || session.started_by.email || '—'}
          </div>
        )}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {canStart ? (
          <Button variant="accent" onClick={onStart} disabled={busy}>
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />} Iniciar
          </Button>
        ) : (
          <>
            <Button variant="soft" onClick={onOpen}>Abrir</Button>
            <Button variant="ghost" onClick={onStop} title="Detener">
              <Square size={14} />
            </Button>
          </>
        )}
      </div>
    </Card>
  )
}
