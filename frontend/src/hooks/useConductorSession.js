import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'

/* Streaming de una sesión de Conductor: hidrata con el buffer de replay
   (GET /sessions/{id}) y luego abre el WebSocket para los eventos en vivo.
   No reconecta solo — si el socket se corta, el usuario vuelve a abrir la
   sesión desde su RoleCard y esto se remonta con el historial ya guardado
   en el backend (el buffer de replay vive ahí, no acá).

   Dos flujos distintos llegan por el mismo socket:
   - eventos AUTORITATIVOS (`user`, `assistant`, `status`, `result`) → van a
     `messages`, son los que se reproducen al reabrir.
   - `stream_event` (deltas token a token de --include-partial-messages) → NO
     van a `messages`; se acumulan en `streaming`, que es texto en vuelo y se
     descarta apenas llega el `assistant` con el bloque ya completo. Guardar
     los deltas además del texto final duplicaría cada respuesta en pantalla. */
export function useConductorSession(sessionId) {
  const [status, setStatus] = useState('loading') // loading | connecting | open | closed | error
  const [session, setSession] = useState(null)
  const [messages, setMessages] = useState([])
  const [streaming, setStreaming] = useState('')
  const wsRef = useRef(null)

  useEffect(() => {
    if (!sessionId) return
    let cancelled = false
    setStatus('loading')
    setSession(null)
    setMessages([])
    setStreaming('')

    api.conductorSession(sessionId).then(({ session: s, messages: hist }) => {
      if (cancelled) return
      setSession(s)
      setMessages(hist)
      setStatus('connecting')
      const ws = new WebSocket(api.conductorStreamUrl(sessionId))
      wsRef.current = ws
      ws.onopen = () => !cancelled && setStatus('open')
      ws.onmessage = (ev) => {
        if (cancelled) return
        const event = JSON.parse(ev.data)

        if (event.type === 'stream_event') {
          const inner = event.event || {}
          if (inner.type === 'content_block_delta' && inner.delta?.type === 'text_delta') {
            setStreaming((s) => s + inner.delta.text)
          }
          return   // nunca entra a `messages`
        }

        setMessages((m) => [...m, event])
        // El bloque ya llegó completo y autoritativo: el texto en vuelo sobra.
        if (event.type === 'assistant' || event.type === 'result') setStreaming('')
        if (event.type === 'status') {
          setSession((prev) => (prev ? {
            ...prev, status: event.status, exit_code: event.exit_code,
            stderr_tail: event.stderr_tail,
          } : prev))
        }
        if (event.type === 'result') {
          setSession((prev) => (prev ? { ...prev, turn_in_flight: false } : prev))
        }
      }
      ws.onclose = () => !cancelled && setStatus('closed')
    }).catch(() => !cancelled && setStatus('error'))

    return () => {
      cancelled = true
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [sessionId])

  // No se agrega el mensaje del usuario acá: el backend lo registra al
  // aceptarlo y lo reparte por el mismo socket (ver conductor.py::send_turn),
  // así que llega por `messages` como cualquier otro evento. Una sola fuente
  // de verdad, y el historial al reabrir coincide con lo que se vio en vivo.
  const sendTurn = useCallback(async (text) => {
    if (!sessionId || !text.trim()) return
    setSession((prev) => (prev ? { ...prev, turn_in_flight: true } : prev))
    try {
      await api.conductorSendTurn(sessionId, text.trim())
    } catch (e) {
      setSession((prev) => (prev ? { ...prev, turn_in_flight: false } : prev))
      throw e
    }
  }, [sessionId])

  const stop = useCallback(async () => {
    if (!sessionId) return
    const { session: s } = await api.conductorStop(sessionId)
    setSession(s)
  }, [sessionId])

  return { status, session, messages, streaming, sendTurn, stop }
}
