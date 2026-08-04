import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'

/* Streaming de una sesión de Conductor: hidrata con el buffer de replay
   (GET /sessions/{id}) y luego abre el WebSocket para los eventos en vivo.
   No reconecta solo — si el socket se corta, el usuario vuelve a abrir la
   sesión desde su RoleCard y esto se remonta con el historial ya guardado
   en el backend (el buffer de replay vive ahí, no acá). */
export function useConductorSession(sessionId) {
  const [status, setStatus] = useState('loading') // loading | connecting | open | closed | error
  const [session, setSession] = useState(null)
  const [messages, setMessages] = useState([])
  const wsRef = useRef(null)

  useEffect(() => {
    if (!sessionId) return
    let cancelled = false
    setStatus('loading')
    setSession(null)
    setMessages([])

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
        setMessages((m) => [...m, event])
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

  const sendTurn = useCallback(async (text) => {
    if (!sessionId || !text.trim()) return
    setSession((prev) => (prev ? { ...prev, turn_in_flight: true } : prev))
    await api.conductorSendTurn(sessionId, text.trim())
  }, [sessionId])

  const stop = useCallback(async () => {
    if (!sessionId) return
    const { session: s } = await api.conductorStop(sessionId)
    setSession(s)
  }, [sessionId])

  return { status, session, messages, sendTurn, stop }
}
