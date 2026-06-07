import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Phone } from 'lucide-react'
import { api } from '../lib/api'
import { Card, Button, Input, Select } from '../components/ui'

export default function Llamadas() {
  const agentsQ = useQuery({ queryKey: ['assistants'], queryFn: api.assistants, retry: false })
  const numbersQ = useQuery({ queryKey: ['vapiNumbers'], queryFn: api.vapiNumbers, retry: false })

  const [agent, setAgent] = useState('')
  const [num, setNum] = useState('')
  const [digits, setDigits] = useState('')
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)

  if (agentsQ.isError) {
    return (
      <Card className="p-6 max-w-xl">
        <div className="font-semibold mb-1">Llamadas con IA</div>
        <div className="text-sm text-zinc-500 mb-2">
          Falta tu <b>VAPI_API_KEY</b>. Conéctala en Configuración y volvé.
        </div>
        <div className="text-xs text-zinc-400 mb-3">({agentsQ.error.message})</div>
        <Link to="/config" className="text-emerald-700 text-sm font-medium">Ir a Configuración →</Link>
      </Card>
    )
  }

  const agents = agentsQ.data || []
  const numbers = numbersQ.data || []

  const call = async () => {
    const d = digits.replace(/\D/g, '')
    if (d.length !== 9) { setMsg({ ok: false, t: 'Escribe los 9 dígitos (el 9 + 8 más).' }); return }
    setBusy(true); setMsg(null)
    try {
      await api.call({ number: '+56' + d, assistant_id: agent || agents[0]?.id, phone_number_id: num || numbers[0]?.id })
      setMsg({ ok: true, t: 'Llamada iniciada a +56' + d + '. Te debería sonar el teléfono.' })
    } catch (e) { setMsg({ ok: false, t: e.message }) } finally { setBusy(false) }
  }

  return (
    <Card className="p-6 max-w-xl space-y-4">
      <div>
        <div className="font-semibold">Llamar con un agente</div>
        <div className="text-sm text-zinc-500">Elegí el agente de voz y llamá. Probá con tu celular primero.</div>
      </div>

      <div>
        <label className="block text-xs text-zinc-500 mb-1">Agente de voz</label>
        {agents.length ? (
          <Select className="w-full" value={agent} onChange={(e) => setAgent(e.target.value)}>
            {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </Select>
        ) : <div className="text-sm text-rose-600">No tienes agentes en Vapi.</div>}
      </div>

      <div>
        <label className="block text-xs text-zinc-500 mb-1">Número de origen</label>
        {numbers.length ? (
          <Select className="w-full" value={num} onChange={(e) => setNum(e.target.value)}>
            {numbers.map((n) => <option key={n.id} value={n.id}>{n.number}</option>)}
          </Select>
        ) : <div className="text-sm text-rose-600">No tienes números en Vapi (Phone Numbers).</div>}
      </div>

      <div>
        <label className="block text-xs text-zinc-500 mb-1">Llamar a</label>
        <div className="flex gap-2">
          <span className="inline-flex items-center gap-1.5 border border-zinc-200 rounded-xl px-3 py-2 text-sm bg-zinc-50 whitespace-nowrap">🇨🇱 +56</span>
          <Input inputMode="numeric" maxLength={11} placeholder="9 1234 5678" value={digits} onChange={(e) => setDigits(e.target.value)} />
          <Button variant="accent" onClick={call} disabled={busy}><Phone size={15} />{busy ? 'Llamando…' : 'Llamar'}</Button>
        </div>
      </div>

      {msg && <div className={'text-sm ' + (msg.ok ? 'text-emerald-700' : 'text-rose-600')}>{msg.ok ? '✓ ' : ''}{msg.t}</div>}
    </Card>
  )
}
