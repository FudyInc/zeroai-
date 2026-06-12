import { useState } from 'react'
import { MessageSquare } from 'lucide-react'
import { api } from '../lib/api'
import { Card, Button, Input } from './ui'

/* Prueba el agente conversacional: escribe como si fueras un lead y mira cómo responde
   usando el negocio del cliente (su ICP guardado). En mock da respuestas por intención;
   con Anthropic key responde el modelo real. Compartido entre Config y la página de
   WhatsApp. */
export default function AgentTester({
  title = 'Probar el agente de respuestas',
  hint = 'Escribe como si fueras un lead. Responde con el negocio del cliente (su ICP). Mock por intención · con Anthropic key, modelo real.',
  defaultClient = 'demo',
}) {
  const [client, setClient] = useState(defaultClient)
  const [msg, setMsg] = useState('')
  const [chat, setChat] = useState([])
  const [busy, setBusy] = useState(false)
  const send = async () => {
    const text = msg.trim()
    if (!text) return
    setMsg(''); setBusy(true)
    setChat((c) => [...c, { who: 'lead', text }])
    try {
      const { reply, mode } = await api.simulateAgent({ client: client.trim() || 'demo', message: text })
      setChat((c) => [...c, { who: 'agent', text: reply, mode }])
    } catch (e) {
      setChat((c) => [...c, { who: 'agent', text: 'Error: ' + e.message, mode: 'error' }])
    } finally { setBusy(false) }
  }
  return (
    <Card className="p-6">
      <div className="font-semibold flex items-center gap-2">
        <MessageSquare size={16} /> {title}
      </div>
      <div className="text-xs text-zinc-400 mt-0.5 mb-3">{hint}</div>
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xs text-zinc-500">Cliente:</span>
        <Input value={client} onChange={(e) => setClient(e.target.value)} className="w-40" placeholder="demo" />
      </div>
      {chat.length > 0 && (
        <div className="space-y-2 mb-3 max-h-72 overflow-auto rounded-xl bg-zinc-50 p-3">
          {chat.map((m, i) => (
            <div key={i} className={m.who === 'lead' ? 'text-right' : 'text-left'}>
              <span className={'inline-block rounded-2xl px-3 py-1.5 text-sm ' +
                (m.who === 'lead' ? 'bg-brand text-white' : 'bg-white border border-zinc-200 text-zinc-700')}>
                {m.text}
              </span>
              {m.who === 'agent' && m.mode && <div className="text-[10px] text-zinc-400 mt-0.5">{m.mode}</div>}
            </div>
          ))}
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
