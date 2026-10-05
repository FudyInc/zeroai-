import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MessageCircle, RefreshCw, Send } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { Button, Card } from './ui'

function when(seconds) {
  if (!seconds) return ''
  return new Date(seconds * 1000).toLocaleString('es-CL', { dateStyle: 'short', timeStyle: 'short' })
}

export default function WhatsAppWebInbox({ client, expectedNumber }) {
  const [selected, setSelected] = useState('')
  const [draft, setDraft] = useState('')
  const [filter, setFilter] = useState('')
  const qc = useQueryClient()
  useEffect(() => { setSelected(''); setDraft('') }, [client])
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
  const rows = (chats.data?.chats || []).filter((chat) =>
    `${chat.name} ${chat.id}`.toLowerCase().includes(filter.toLowerCase()))
  const current = messages.data?.chat || rows.find((chat) => chat.id === selected)
  const canReply = /^\d{8,20}@(c\.us|lid)$/.test(selected)

  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="font-display font-bold text-brand flex items-center gap-2"><MessageCircle size={18} /> WhatsApp Web · chats</h2>
          <p className="text-xs text-zinc-500 mt-1">Bandeja del número asignado a {client}.</p>
        </div>
        <Button variant="soft" onClick={() => { status.refetch(); chats.refetch(); if (selected) messages.refetch() }} title="Actualizar chats"><RefreshCw size={14} /> Actualizar</Button>
      </div>

      {status.isError && <p className="text-sm text-amber-700 mt-4">{status.error.message}. Inicia el puente local para vincular tu cuenta y ver los chats.</p>}
      {status.data?.state === 'ready' && !ready && <p className="text-sm text-amber-700 mt-4">El número conectado no coincide con el asignado a {client}. La bandeja queda bloqueada para evitar responder desde otra empresa.</p>}
      {status.data?.state === 'scan_qr' && status.data.qr && (
        <div className="mt-4 flex flex-wrap items-center gap-4">
          <img src={status.data.qr} alt="Código QR para vincular WhatsApp Web" className="w-48 h-48 rounded-xl bg-white p-2" />
          <p className="text-sm text-zinc-600 max-w-sm">En el teléfono, abre WhatsApp → Dispositivos vinculados → Vincular dispositivo y escanea el código.</p>
        </div>
      )}
      {!status.isError && !ready && status.data?.state !== 'scan_qr' && (
        <p className="text-sm text-zinc-500 mt-4">Estado de conexión: {status.data?.state || 'consultando…'}{status.data?.error ? ` · ${status.data.error}` : ''}</p>
      )}
      {ready && (
        <>
          <p className="text-xs text-emerald-700 mt-3">Conectado: {status.data.account || 'WhatsApp Web'}</p>
          <div className="grid grid-cols-1 lg:grid-cols-[minmax(220px,320px)_1fr] border border-zinc-200 rounded-xl overflow-hidden mt-4 min-h-[430px]">
            <div className="border-b lg:border-b-0 lg:border-r border-zinc-200">
              <div className="p-3 border-b border-zinc-100">
                <input type="search" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Buscar chat"
                  aria-label="Buscar chat" className="w-full border border-zinc-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-gold" />
              </div>
              <div className="overflow-y-auto max-h-[390px]">
                {chats.isError && <p className="p-3 text-sm text-rose-600">{chats.error.message}</p>}
                {chats.isLoading && <p className="p-3 text-sm text-zinc-400">Cargando chats…</p>}
                {!chats.isLoading && !chats.isError && rows.length === 0 && <p className="p-3 text-sm text-zinc-400">No hay chats para mostrar.</p>}
                {rows.map((chat) => (
                  <button key={chat.id} onClick={() => setSelected(chat.id)}
                    className={'w-full text-left px-3 py-3 border-b border-zinc-100 hover:bg-zinc-50 ' + (selected === chat.id ? 'bg-champagne/30' : '')}>
                    <div className="flex justify-between gap-2 text-sm"><b className="truncate">{chat.name}</b><span className="text-[10px] text-zinc-400 shrink-0">{when(chat.timestamp)}</span></div>
                    <div className="flex items-center gap-2 mt-1 text-xs text-zinc-500"><span className="truncate flex-1">{chat.lastFromMe ? 'Tú: ' : ''}{chat.lastMessage || 'Sin mensajes'}</span>{chat.unreadCount > 0 && <span className="bg-emerald-600 text-white rounded-full px-1.5">{chat.unreadCount}</span>}</div>
                  </button>
                ))}
              </div>
            </div>
            <div className="flex flex-col min-h-[430px]">
              {!selected ? <div className="flex-1 grid place-items-center text-sm text-zinc-400 p-6">Selecciona un chat para ver sus mensajes.</div> : (
                <>
                  <div className="px-4 py-3 border-b border-zinc-100 font-semibold text-sm truncate">{current?.name || selected}</div>
                  <div className="flex-1 overflow-y-auto max-h-[420px] p-4 space-y-2 bg-zinc-50/50" aria-live="polite">
                    {messages.isLoading && <p className="text-sm text-zinc-400">Cargando conversación…</p>}
                    {messages.isError && <p className="text-sm text-rose-600">{messages.error.message}</p>}
                    {messages.data?.messages?.map((message) => (
                      <div key={message.id} className={'flex ' + (message.fromMe ? 'justify-end' : 'justify-start')}>
                        <div className={'max-w-[85%] rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap break-words ' + (message.fromMe ? 'bg-champagne/60' : 'bg-white border border-zinc-100')}>
                          {message.author && <div className="text-[10px] font-semibold text-zinc-500">{message.author}</div>}
                          <div>{message.body}</div><div className="text-[10px] text-zinc-400 mt-1 text-right">{when(message.timestamp)}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                  {!canReply && <p className="px-3 pt-3 text-xs text-zinc-500">Solo se puede responder desde chats individuales.</p>}
                  <form className="flex gap-2 p-3 border-t border-zinc-100" onSubmit={(event) => { event.preventDefault(); if (canReply && draft.trim() && !send.isPending) send.mutate(draft.trim()) }}>
                    <input value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={4096} placeholder="Escribe una respuesta" aria-label="Mensaje"
                      className="flex-1 min-w-0 border border-zinc-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-gold" />
                    <Button type="submit" disabled={!canReply || !draft.trim() || send.isPending}><Send size={14} /> Enviar</Button>
                  </form>
                </>
              )}
            </div>
          </div>
        </>
      )}
    </Card>
  )
}
