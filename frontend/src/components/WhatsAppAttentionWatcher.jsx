import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { attentionCaseKey, attentionOf, handoffKey, unseenAttentionCases, unseenHumanRequests } from '../lib/whatsapp-attention'

// Lleva a la sección «Atención» de /whatsapp. Si la página aún no montó, reintenta
// unos instantes hasta que exista el ancla.
function scrollToAttention() {
  let tries = 0
  const go = () => {
    const el = document.getElementById('wa-atencion')
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    else if (tries++ < 10) setTimeout(go, 150)
  }
  setTimeout(go, 50)
}

export default function WhatsAppAttentionWatcher({ client, enabled, onOpen }) {
  const seenRef = useRef(new Set())
  const attnSeenRef = useRef(new Set())
  const nav = useNavigate()
  const readiness = useQuery({
    queryKey: ['whatsapp-readiness', client], queryFn: () => api.whatsappReadiness(client),
    enabled: enabled && client === 'losetaschile', refetchInterval: 30000, retry: false,
  })
  // Corre en todas las pantallas: con el puente listo basta cada 15 s; caído o
  // sin conectar, cada 60 s, para no insistir sobre un puente que no responde.
  const status = useQuery({
    queryKey: ['whatsapp-web-status', client], queryFn: () => api.whatsappWebStatus(client),
    enabled: enabled && client === 'losetaschile', retry: false,
    refetchInterval: (query) => (query.state.data?.state === 'ready' ? 15000 : 60000),
  })
  // Misma clave que el contador del menú: una sola petición compartida.
  const attention = useQuery({
    queryKey: ['whatsapp-attention', client], queryFn: () => api.whatsappAttention(client),
    enabled: enabled && !!client, refetchInterval: 30000, retry: false,
  })
  const account = status.data?.account || ''
  // Mismo criterio que la bandeja (WhatsAppWebInbox): número exacto. Si la bandeja
  // bloquea los chats por número distinto, el aviso tampoco debe mostrarlos.
  const ready = enabled && client === 'losetaschile' && !readiness.isError && !status.isError &&
    status.data?.state === 'ready' && !!readiness.data?.number && account === readiness.data.number
  // Misma clave e intervalo que la bandeja (WhatsAppWebInbox): en /whatsapp ambos
  // comparten una sola consulta en vez de golpear el puente dos veces.
  const chats = useQuery({
    queryKey: ['whatsapp-web-chats', client], queryFn: () => api.whatsappWebChats(client),
    enabled: ready, refetchInterval: 10000, retry: false,
  })

  useEffect(() => {
    try { seenRef.current = new Set(JSON.parse(sessionStorage.getItem(`zero-wa-alerted:${client}`) || '[]')) }
    catch { seenRef.current = new Set() }
  }, [client])
  useEffect(() => {
    try { attnSeenRef.current = new Set(JSON.parse(sessionStorage.getItem(`zero-wa-attention-seen:${client}`) || '[]')) }
    catch { attnSeenRef.current = new Set() }
  }, [client])
  useEffect(() => {
    if (!attention.data?.items) return
    const fresh = unseenAttentionCases(attention.data.items, attnSeenRef.current)
    if (!fresh.length) return
    fresh.forEach((item) => attnSeenRef.current.add(attentionCaseKey(item)))
    try { sessionStorage.setItem(`zero-wa-attention-seen:${client}`, JSON.stringify([...attnSeenRef.current].slice(-100))) }
    catch { /* El contador del menú sigue mostrando los casos abiertos. */ }
    const respond = { label: 'Responder', onClick: () => { nav('/whatsapp'); scrollToAttention() } }
    fresh.slice(0, 2).forEach((item) => toast.warning('El agente necesita ayuda', {
      id: `attention:${client}:${attentionCaseKey(item)}`,
      className: 'wa-attention-toast',
      description: item.pregunta,
      duration: 8000,
      action: respond,
    }))
    if (fresh.length > 2) toast.warning(`${fresh.length - 2} casos más necesitan tu ayuda`, {
      id: `attention-summary:${client}`,
      className: 'wa-attention-toast',
      duration: 8000,
      action: { ...respond, label: 'Ver casos' },
    })
  }, [attention.data, client, nav])
  useEffect(() => {
    if (!ready || !chats.data?.chats) return
    const mode = readiness.data?.response_mode
    const fresh = unseenHumanRequests(chats.data.chats, seenRef.current, mode)
    if (!fresh.length) return
    fresh.forEach((chat) => seenRef.current.add(handoffKey(chat, mode)))
    try { sessionStorage.setItem(`zero-wa-alerted:${client}`, JSON.stringify([...seenRef.current].slice(-100))) }
    catch { /* El aviso en pantalla sigue disponible si el navegador bloquea sessionStorage. */ }
    fresh.slice(0, 2).forEach((chat) => toast.warning('Conversación requiere atención', {
      id: `handoff:${client}:${handoffKey(chat, mode)}`,
      className: 'wa-attention-toast',
      description: `${chat.name || chat.id} · ${attentionOf(chat, mode).reason}`,
      duration: 7000,
      action: { label: 'Abrir chat', onClick: () => onOpen(chat.id, client) },
    }))
    if (fresh.length > 2) toast.warning(`${fresh.length - 2} conversaciones más necesitan atención`, {
      id: `handoff-summary:${client}`,
      className: 'wa-attention-toast',
      duration: 7000,
      action: { label: 'Ver lista', onClick: () => onOpen('', client) },
    })
  }, [chats.data, client, ready, readiness.data?.response_mode, onOpen])

  return null
}
