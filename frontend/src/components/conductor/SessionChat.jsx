import { useEffect, useRef, useState } from 'react'
import { X, Send, Square, Wrench } from 'lucide-react'
import { Card, Button, Eyebrow } from '../ui'
import { cn } from '../../lib/util'
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

/* De los eventos del CLI nos quedamos con lo que se lee como conversación:
   los turnos del humano (`user`), el texto del asistente y sus tool_use. El
   resto (system/init, rate_limit, result) es telemetría, no chat.

   `content` llega como string suelto o como lista de bloques según de dónde
   venga el evento — se normaliza acá para recorrer ambos igual. */
function renderableItems(messages) {
  const items = []
  messages.forEach((e, i) => {
    if (e.type !== 'assistant' && e.type !== 'user') return
    const content = e.message?.content
    const blocks = typeof content === 'string' ? [{ type: 'text', text: content }] : (content || [])
    for (const block of blocks) {
      if (block.type === 'text' && block.text) {
        items.push({ key: `${i}-${items.length}`, kind: 'text', role: e.type, text: block.text })
      } else if (block.type === 'tool_use') {
        items.push({ key: `${i}-${items.length}`, kind: 'tool', line: toolLine(block.name, block.input) })
      }
    }
  })
  return items
}

/* Transcripción + input de una sesión. El humano a la derecha en slate, el
   agente a la izquierda sobre la superficie — la jerarquía la da el contraste,
   no un color por interlocutor. */
export default function SessionChat({ sessionId, onClose }) {
  const { status, session, messages, streaming, sendTurn, stop } = useConductorSession(sessionId)
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const bottomRef = useRef(null)
  const taRef = useRef(null)

  const running = session?.status === 'running'
  const turnInFlight = !!session?.turn_in_flight
  const items = renderableItems(messages)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [items.length, streaming])

  // Autogrow: el textarea crece con el prompt hasta un techo y ahí scrollea.
  useEffect(() => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 160) + 'px'
  }, [text])

  const send = async () => {
    const t = text.trim()
    if (!t || sending || turnInFlight || !running) return
    setText(''); setSending(true)
    try { await sendTurn(t) } catch { setText(t) } finally { setSending(false) }
  }

  // Enter envía; Shift+Enter hace salto de línea. Estos prompts son de varias
  // líneas casi siempre — con un <input> de una sola línea no se podían
  // escribir.
  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="min-w-0">
          <Eyebrow>{session ? (STATUS_LABEL[session.status] || session.status) : 'cargando'}</Eyebrow>
          <div className="font-display text-sm font-semibold tracking-tight text-zinc-800 truncate mt-0.5">
            {session ? session.role_label : '—'}
            <span className="font-sans font-normal text-pewter">
              {session?.worktree_branch ? ` · ${session.worktree_branch}` : ''}
              {session?.model ? ` · ${session.model}` : ''}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {running && (
            <Button variant="ghost" onClick={stop} title="Detener sesión">
              <Square size={14} />
            </Button>
          )}
          <button onClick={onClose} className="text-pewter hover:text-zinc-600" aria-label="Cerrar">
            <X size={16} />
          </button>
        </div>
      </div>

      <div className="space-y-2.5 mb-3 max-h-[28rem] overflow-auto rounded-xl bg-zinc-50 p-3.5">
        {items.length === 0 && !streaming && (
          <div className="text-xs text-pewter text-center py-6">
            {status === 'connecting' || status === 'loading'
              ? 'Conectando…'
              : 'Sin mensajes todavía — escribe abajo para darle la primera instrucción.'}
          </div>
        )}

        {items.map((item) => {
          if (item.kind === 'tool') {
            return (
              <div key={item.key} className="text-[11px] text-pewter pl-1 flex items-center gap-1.5 font-mono">
                <Wrench size={11} className="shrink-0" /> {item.line}
              </div>
            )
          }
          const mine = item.role === 'user'
          return (
            <div key={item.key} className={cn('flex', mine ? 'justify-end' : 'justify-start')}>
              <span className={cn(
                'inline-block rounded-2xl px-3.5 py-2 text-sm whitespace-pre-wrap max-w-[85%]',
                mine
                  ? 'bg-brand text-white'
                  : 'bg-white dark:bg-[#1D2016] border border-zinc-200 text-zinc-700',
              )}>
                {item.text}
              </span>
            </div>
          )
        })}

        {/* Texto en vuelo: los deltas token a token que todavía no cierran en
            un evento `assistant`. El cursor deja ver que sigue escribiendo. */}
        {streaming && (
          <div className="flex justify-start">
            <span className="inline-block rounded-2xl px-3.5 py-2 text-sm whitespace-pre-wrap max-w-[85%] bg-white dark:bg-[#1D2016] border border-zinc-200 text-zinc-700">
              {streaming}
              <span className="inline-block w-[2px] h-3.5 -mb-0.5 ml-0.5 bg-pewter animate-pulse" />
            </span>
          </div>
        )}

        {turnInFlight && !streaming && (
          <div className="text-xs text-pewter pl-1">pensando…</div>
        )}
        <div ref={bottomRef} />
      </div>

      {!running && session && (
        <div className="text-xs text-amber-700 bg-amber-50 rounded-xl px-3 py-2 mb-3">
          Esta sesión ya no está corriendo ({STATUS_LABEL[session.status] || session.status}
          {session.exit_code != null ? `, código ${session.exit_code}` : ''}). Inicia una nueva desde la fila de arriba.
          {session.stderr_tail?.length > 0 && (
            <pre className="mt-2 text-[10px] text-amber-800/80 whitespace-pre-wrap max-h-24 overflow-auto">
              {session.stderr_tail.join('\n')}
            </pre>
          )}
        </div>
      )}

      <div className="flex gap-2 items-end">
        <textarea
          ref={taRef} rows={1} value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={!running}
          placeholder={running ? 'Escríbele a esta terminal…  (Shift+Enter para salto de línea)' : 'Sesión terminada'}
          className={cn(
            'w-full border border-zinc-200 rounded-xl px-3 py-2 text-sm outline-none transition resize-none',
            'focus:ring-4 focus:ring-champagne/40 focus:border-gold/60 placeholder:text-zinc-400',
            'disabled:opacity-50',
          )}
        />
        <Button variant="primary" onClick={send} disabled={!running || sending || turnInFlight}>
          {sending || turnInFlight ? '…' : <Send size={14} />}
        </Button>
      </div>
    </Card>
  )
}
