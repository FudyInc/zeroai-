import { useEffect, useState } from 'react'
import { MessageSquare, RotateCcw, AlertTriangle } from 'lucide-react'
import { api } from '../lib/api'
import { Card, Button, Input } from './ui'
import QuoteCard from './QuoteCard'

/* Prueba el agente conversacional: escribe como si fueras un lead y mira cómo responde
   usando el negocio del cliente (su ficha e ICP guardados). El servidor no guarda estos
   ensayos: la transcripción vive acá y se manda completa (history) en cada turno.
   Compartido entre Config, WhatsApp y Agentes. Con `fixedClient` se oculta el campo de
   cliente; con `vendorId` se prueba una personalidad sin asignarla. */
export default function AgentTester({
  title = 'Probar el agente de respuestas',
  hint = 'Escribe como si fueras un lead y mira qué contesta. Nada de esto le llega a un lead real.',
  defaultClient = 'demo',
  fixedClient = null,
  vendorId = null,
  vendorName = null,
}) {
  const [client, setClient] = useState(defaultClient)
  const [msg, setMsg] = useState('')
  const [chat, setChat] = useState([])
  const [busy, setBusy] = useState(false)
  const [mockMode, setMockMode] = useState(false)

  // Cambiar de personalidad o de cliente arranca una conversación nueva.
  useEffect(() => { setChat([]); setMockMode(false) }, [vendorId, fixedClient])

  const theClient = (fixedClient ?? client).trim() || 'demo'
  const send = async () => {
    const text = msg.trim()
    if (!text || busy) return
    const history = chat
      .filter((m) => m.mode !== 'error')
      .map((m) => ({ role: m.who === 'lead' ? 'lead' : 'agent', text: m.text }))
    setMsg(''); setBusy(true)
    setChat((c) => [...c, { who: 'lead', text }])
    try {
      const body = { client: theClient, message: text, history }
      if (vendorId) body.vendor_id = vendorId
      const { reply, mode, quote } = await api.simulateAgent(body)
      setMockMode(mode === 'mock')
      setChat((c) => [...c, { who: 'agent', text: reply, mode, quote }])
    } catch (e) {
      setChat((c) => [...c, { who: 'agent', text: 'Error: ' + e.message, mode: 'error' }])
    } finally { setBusy(false) }
  }

  return (
    <Card className="p-6">
      <div className="flex items-center justify-between gap-2">
        <div className="font-semibold flex items-center gap-2">
          <MessageSquare size={16} /> {title}
        </div>
        {chat.length > 0 && (
          <button onClick={() => { setChat([]); setMockMode(false) }}
            className="text-xs text-zinc-400 hover:text-zinc-600 inline-flex items-center gap-1">
            <RotateCcw size={12} /> Reiniciar
          </button>
        )}
      </div>
      <div className="text-xs text-zinc-400 mt-0.5 mb-3">
        {hint}{vendorName ? <> Estás hablando con <b className="text-zinc-500">{vendorName}</b>.</> : null}
      </div>
      {!fixedClient && (
        <div className="flex items-center gap-2 mb-3">
          <span className="text-xs text-zinc-500">Cliente:</span>
          <Input value={client} onChange={(e) => { setClient(e.target.value); setChat([]) }} className="w-40" placeholder="demo" />
        </div>
      )}
      {mockMode && (
        <div className="flex items-start gap-1.5 text-xs text-amber-700 bg-amber-50 rounded-xl px-3 py-2 mb-3">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          Sin modelo configurado: las respuestas son simuladas. Revisa Configuración para conectar el cerebro.
        </div>
      )}
      {chat.length > 0 && (
        <div className="space-y-2 mb-3 max-h-72 overflow-auto rounded-xl bg-zinc-50 p-3">
          {chat.map((m, i) => (
            <div key={i} className={m.who === 'lead' ? 'text-right' : 'text-left'}>
              <span className={'inline-block rounded-2xl px-3 py-1.5 text-sm ' +
                (m.who === 'lead' ? 'bg-brand text-white' : 'bg-white dark:bg-[#1D2016] border border-zinc-200 text-zinc-700')}>
                {m.text}
              </span>
              {m.quote && <div className="mt-1.5"><QuoteCard quote={m.quote} /></div>}
            </div>
          ))}
          {busy && <div className="text-left text-xs text-zinc-400 pl-1">escribiendo…</div>}
        </div>
      )}
      <div className="flex gap-2">
        <Input value={msg} onChange={(e) => setMsg(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          placeholder="¿cuánto cuesta? / ¿qué hacen? / ¿eres un bot?" />
        <Button variant="accent" onClick={send} disabled={busy}>{busy ? '…' : 'Enviar'}</Button>
      </div>
    </Card>
  )
}
