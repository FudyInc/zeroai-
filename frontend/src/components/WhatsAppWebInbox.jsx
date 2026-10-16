import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, MessageCircle, RefreshCw, Search, Send } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { Button, Card } from './ui'

function when(seconds) {
  if (!seconds) return ''
  return new Date(seconds * 1000).toLocaleString('es-CL', { dateStyle: 'short', timeStyle: 'short' })
}

function ChatAvatar({ name }) {
  const initials = String(name || '?').trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toLocaleUpperCase('es-CL') || '?'
  return <span className="wa-chat-avatar" aria-hidden="true">{initials}</span>
}

export default function WhatsAppWebInbox({ client, expectedNumber, responseMode }) {
  const location = useLocation()
  const nav = useNavigate()
  const [selected, setSelected] = useState('')
  const [draft, setDraft] = useState('')
  const [filter, setFilter] = useState('')
  const qc = useQueryClient()
  useEffect(() => { setSelected(''); setDraft(''); setFilter('') }, [client])
  // "Abrir chat" desde el aviso global llega como location.state. Se consume una
  // sola vez y se borra del historial: si no, atrás/adelante o F5 reabrirían el
  // chat. Si el aviso era de otro negocio, no se selecciona un chat ajeno.
  useEffect(() => {
    const wanted = location.state?.waChat
    if (!wanted) return
    if (!location.state.client || location.state.client === client) setSelected(wanted)
    nav(location.pathname, { replace: true, state: null })
  }, [location.key])   // eslint-disable-line react-hooks/exhaustive-deps
  const status = useQuery({ queryKey: ['whatsapp-web-status', client], queryFn: () => api.whatsappWebStatus(client), refetchInterval: 5000, retry: false })
  const ready = status.data?.state === 'ready' && !!expectedNumber && status.data.account === expectedNumber
  const chats = useQuery({ queryKey: ['whatsapp-web-chats', client], queryFn: () => api.whatsappWebChats(client), enabled: ready, refetchInterval: 10000, retry: false })
  const messages = useQuery({ queryKey: ['whatsapp-web-messages', client, selected], queryFn: () => api.whatsappWebMessages(client, selected), enabled: ready && !!selected, refetchInterval: 5000, retry: false })
  const send = useMutation({
    mutationFn: (text) => api.whatsappWebReply(client, selected, text),
    onSuccess: () => {
      setDraft('')
      qc.invalidateQueries({ queryKey: ['whatsapp-web-messages', client, selected] })
      qc.invalidateQueries({ queryKey: ['whatsapp-web-chats', client] })
    },
    onError: (error) => toast.error('No se pudo enviar: ' + error.message),
  })
  const handoff = useMutation({
    mutationFn: (active) => api.whatsappWebHandoff(client, selected, active),
    onSuccess: (_data, active) => {
      qc.invalidateQueries({ queryKey: ['whatsapp-web-messages', client, selected] })
      qc.invalidateQueries({ queryKey: ['whatsapp-web-chats', client] })
      toast.success(active ? 'Chat asignado al equipo' :
        responseMode === 'manual' ? 'Derivación cerrada; el negocio sigue en modo manual' :
        'Agente reactivado para este chat')
    },
    onError: (error) => toast.error('No se pudo cambiar la atención: ' + error.message),
  })
  const allChats = chats.data?.chats || []
  const rows = allChats.filter((chat) =>
    `${chat.name || ''} ${chat.id || ''}`.toLowerCase().includes(filter.toLowerCase()))
    .sort((a, b) => Number(!!b.handoff) - Number(!!a.handoff))
  const pendingHuman = allChats.filter((chat) => !!chat.handoff).length
  const unread = allChats.filter((chat) => chat.unreadCount > 0).length
  const current = messages.data?.chat || allChats.find((chat) => chat.id === selected)
  const activeHandoff = messages.data?.handoff || allChats.find((chat) => chat.id === selected)?.handoff

  return (
    <Card className="wa-inbox">
      <div className="wa-inbox-heading">
        <div>
          <div className="wa-field-kicker">WhatsApp Web</div>
          <h3><MessageCircle size={19} /> Conversaciones</h3>
          <p>Bandeja del número asignado a {client}.</p>
        </div>
        <Button variant="soft" onClick={() => { status.refetch(); chats.refetch(); if (selected) messages.refetch() }}
          title="Actualizar chats" disabled={status.isFetching || chats.isFetching || messages.isFetching}>
          <RefreshCw size={14} className={status.isFetching || chats.isFetching || messages.isFetching ? 'animate-spin' : ''} /> Actualizar
        </Button>
      </div>

      {status.isError && <p role="alert" className="wa-inbox-notice">{status.error.message}. Revisa la conexión de WhatsApp Web.</p>}
      {status.data?.state === 'ready' && !ready && <p role="alert" className="wa-inbox-notice">El número conectado no coincide con el asignado a {client}. La bandeja queda bloqueada para evitar responder desde otra empresa.</p>}
      {status.data?.state === 'scan_qr' && status.data.qr && (
        <div className="wa-inbox-qr">
          <img src={status.data.qr} alt="Código QR para vincular WhatsApp Web" />
          <p>En el teléfono, abre WhatsApp → Dispositivos vinculados → Vincular dispositivo y escanea el código.</p>
        </div>
      )}
      {!status.isError && !ready && status.data?.state !== 'scan_qr' && (
        <p className="wa-inbox-state">Estado de conexión: {status.data?.state || 'consultando…'}{status.data?.error ? ` · ${status.data.error}` : ''}</p>
      )}
      {ready && <>
        <div className="wa-inbox-summary">
          <span className="wa-summary-connected"><span className="wa-status-dot is-ready" /> Número conectado</span>
          <span>{allChats.length} conversaciones</span>
          <span>{unread} sin leer</span>
          {pendingHuman > 0 && <span className="wa-summary-human">{pendingHuman} requieren atención humana</span>}
        </div>
        <div className="wa-inbox-layout">
          <div className={'wa-chat-list ' + (selected ? 'has-selection' : '')}>
            <div className="wa-chat-list-heading"><span>Chats</span><span>{allChats.length}</span></div>
            <label className="wa-chat-search"><Search size={16} /><input type="search" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Buscar contacto" aria-label="Buscar chat" /></label>
            <div className="wa-chat-list-scroll">
              {chats.isError && <p role="alert" className="wa-chat-list-message">{chats.error.message}</p>}
              {chats.isLoading && <p className="wa-chat-list-message">Cargando chats…</p>}
              {!chats.isLoading && !chats.isError && rows.length === 0 && <p className="wa-chat-list-message">{filter ? 'No hay contactos con ese nombre.' : 'Todavía no hay conversaciones.'}</p>}
              {rows.map((chat) => (
                <button key={chat.id} type="button" onClick={() => setSelected(chat.id)} aria-current={selected === chat.id ? 'true' : undefined}
                  className={'wa-chat-row ' + (selected === chat.id ? 'is-selected' : '')}>
                  <ChatAvatar name={chat.name || chat.id} />
                  <span className="wa-chat-row-body">
                    <span className="wa-chat-row-top"><strong>{chat.name || chat.id}</strong><time>{when(chat.timestamp)}</time></span>
                    <span className="wa-chat-row-preview">{chat.lastFromMe ? 'Tú: ' : ''}{chat.lastMessage || 'Sin mensajes'}</span>
                    {chat.handoff && <span className="wa-chat-handoff">Atención humana</span>}
                  </span>
                  {chat.unreadCount > 0 && <span className="wa-chat-unread" aria-label={`${chat.unreadCount} mensajes sin leer`}>{chat.unreadCount}</span>}
                </button>
              ))}
            </div>
          </div>
          <div className={'wa-thread ' + (selected ? 'has-selection' : '')}>
            {!selected ? <div className="wa-thread-empty"><span><MessageCircle size={26} /></span><strong>Elige una conversación</strong><p>Selecciona un chat para leer los mensajes y responder desde aquí.</p></div> : <>
              <div className="wa-thread-heading">
                <button type="button" className="wa-thread-back" aria-label="Volver a conversaciones" onClick={() => setSelected('')}><ArrowLeft size={18} /></button>
                <ChatAvatar name={current?.name || selected} />
                <div className="wa-thread-person"><strong>{current?.name || selected}</strong><span>{activeHandoff ? `Atención humana${activeHandoff.reason ? ` · ${activeHandoff.reason}` : ''}` : 'Conversación de WhatsApp'}</span></div>
                <Button variant="soft" disabled={handoff.isPending} onClick={() => handoff.mutate(!activeHandoff)}>
                  {activeHandoff ? (responseMode === 'manual' ? 'Cerrar derivación' : 'Reactivar agente') : 'Tomar chat'}
                </Button>
              </div>
              <div className="wa-thread-messages" aria-live="polite">
                {messages.isLoading && <p className="wa-thread-message-state">Cargando conversación…</p>}
                {messages.isError && <p role="alert" className="wa-thread-message-state">{messages.error.message}</p>}
                {messages.data?.messages?.map((message) => (
                  <div key={message.id} className={'wa-message-row ' + (message.fromMe ? 'is-outgoing' : '')}>
                    <div className="wa-message-bubble">
                      {message.author && <div className="wa-message-author">{message.author}</div>}
                      <div>{message.body}</div><time>{when(message.timestamp)}</time>
                    </div>
                  </div>
                ))}
              </div>
              <form className="wa-thread-compose" onSubmit={(event) => { event.preventDefault(); if (draft.trim() && !send.isPending) send.mutate(draft.trim()) }}>
                <input value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={4096} placeholder="Escribe una respuesta" aria-label="Mensaje" />
                <Button type="submit" disabled={!draft.trim() || send.isPending}><Send size={15} /> Enviar</Button>
              </form>
            </>}
          </div>
        </div>
      </>}
    </Card>
  )
}
