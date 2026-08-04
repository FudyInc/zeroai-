import { useEffect, useRef, useState } from 'react'
import { X, Send, Square, Wrench } from 'lucide-react'
import { Card, Button, Input } from '../ui'
import { useConductorSession } from '../../hooks/useConductorSession'

const STATUS_LABEL = {
  running: 'corriendo', starting: 'iniciando', exited: 'terminada',
  crashed: 'se cayó', killed: 'detenida',
}

// Compacta un tool_use a una línea gris — no es una terminal cruda, pero sí
// deja ver qué está tocando el agente sin construir un renderer por tool.
function toolLine(name, input) {
  const hint = input?.file_path || input?.path || input?.command || input?.pattern || input?.query
  return hint ? `${name}: ${String(hint).slice(0, 90)}` : name
}

// De los eventos crudos del CLI (stream-json), nos quedamos solo con lo que
// se lee como chat: texto de asistente (burbuja) y tool_use (línea gris).
// El resto (system/init, thinking, rate_limit, result, raw) es ruido para
// esta vista — igual queda disponible en session.messages si algún día hace
// falta un log completo.
function renderableItems(messages) {
  const items = []
  messages.forEach((e, i) => {
    if (e.type !== 'assistant') return
    for (const block of e.message?.content || []) {
      if (block.type === 'text' && block.text) {
        items.push({ key: `${i}-${items.length}`, kind: 'text', text: block.text })
      } else if (block.type === 'tool_use') {
        items.push({ key: `${i}-${items.length}`, kind: 'tool', line: toolLine(block.name, block.input) })
      }
    }
  })
  return items
}

/* Transcripción + input de una sesión (lenguaje visual de AgentTester.jsx,
   capa de datos propia: streaming real por WS, no request/response). */
export default function SessionChat({ sessionId, onClose }) {
  const { status, session, messages, sendTurn, stop } = useConductorSession(sessionId)
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const bottomRef = useRef(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages.length])

  const running = session?.status === 'running'
  const turnInFlight = !!session?.turn_in_flight
  const items = renderableItems(messages)

  const send = async () => {
    const t = text.trim()
    if (!t || sending || turnInFlight || !running) return
    setText(''); setSending(true)
    try { await sendTurn(t) } finally { setSending(false) }
  }

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="font-semibold text-sm flex items-center gap-2">
          {session ? `${session.role_emoji} ${session.role_label} · ${session.worktree_branch || '—'}` : 'Cargando…'}
          {session && <span className="text-xs text-zinc-400 font-normal">({STATUS_LABEL[session.status] || session.status})</span>}
        </div>
        <div className="flex items-center gap-2">
          {running && (
            <Button variant="ghost" onClick={stop} title="Detener sesión">
              <Square size={14} />
            </Button>
          )}
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600" aria-label="Cerrar">
            <X size={16} />
          </button>
        </div>
      </div>

      <div className="space-y-2 mb-3 max-h-96 overflow-auto rounded-xl bg-zinc-50 p-3">
        {items.length === 0 && (
          <div className="text-xs text-zinc-400 text-center py-6">
            {status === 'connecting' || status === 'loading' ? 'Conectando…' : 'Sin mensajes todavía — escribe algo abajo.'}
          </div>
        )}
        {items.map((item) => item.kind === 'text' ? (
          <div key={item.key} className="text-left">
            <span className="inline-block rounded-2xl px-3 py-1.5 text-sm bg-white dark:bg-[#1D2016] border border-zinc-200 text-zinc-700 whitespace-pre-wrap">
              {item.text}
            </span>
          </div>
        ) : (
          <div key={item.key} className="text-[11px] text-zinc-400 pl-1 flex items-center gap-1.5">
            <Wrench size={11} className="shrink-0" /> {item.line}
          </div>
        ))}
        {turnInFlight && <div className="text-left text-xs text-zinc-400 pl-1">pensando…</div>}
        <div ref={bottomRef} />
      </div>

      {!running && session && (
        <div className="text-xs text-amber-700 bg-amber-50 rounded-xl px-3 py-2 mb-3">
          Esta sesión ya no está corriendo ({STATUS_LABEL[session.status] || session.status}
          {session.exit_code != null ? `, código ${session.exit_code}` : ''}). Inicia una nueva desde la card de arriba.
          {session.stderr_tail?.length > 0 && (
            <pre className="mt-2 text-[10px] text-amber-800/80 whitespace-pre-wrap max-h-24 overflow-auto">
              {session.stderr_tail.join('\n')}
            </pre>
          )}
        </div>
      )}

      <div className="flex gap-2">
        <Input value={text} onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          disabled={!running}
          placeholder={running ? 'Escríbele a esta terminal…' : 'Sesión terminada'} />
        <Button variant="accent" onClick={send} disabled={!running || sending || turnInFlight}>
          {sending || turnInFlight ? '…' : <Send size={14} />}
        </Button>
      </div>
    </Card>
  )
}
