import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { Link } from 'react-router-dom'
import { Phone } from 'lucide-react'
import { api } from '../lib/api'
import { Card, Button, Input, Select, Skeleton, SectionTitle } from '../components/ui'
import { rise, fade } from '../lib/motion'

export default function Llamadas() {
  const agentsQ = useQuery({ queryKey: ['assistants'], queryFn: api.assistants, retry: false })
  const numbersQ = useQuery({ queryKey: ['vapiNumbers'], queryFn: api.vapiNumbers, retry: false })

  const [agent, setAgent] = useState('')
  const [num, setNum] = useState('')
  const [digits, setDigits] = useState('')
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)

  // Cargando (importante: sin esto, durante la carga mostraba 'No tienes agentes' en rojo).
  if (agentsQ.isLoading || numbersQ.isLoading) {
    return (
      <Card className="p-6 max-w-xl space-y-3">
        <Skeleton className="h-5 w-44" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-10 w-full" />
      </Card>
    )
  }

  // Vapi no configurado (o error de conexión) → estado claro, no un crash.
  if (agentsQ.isError) {
    return (
      <Card className="p-6 max-w-xl">
        <div className="font-semibold mb-1">Llamadas con IA</div>
        <div className="text-sm text-zinc-500 mb-2">
          Este canal usa <b>Vapi</b>. Conecta tu <b>VAPI_API_KEY</b> en Configuración para activarlo.
        </div>
        <div className="text-xs text-zinc-400 mb-3 break-words">({agentsQ.error?.message || 'no disponible'})</div>
        <div className="flex gap-3">
          <Link to="/config" className="text-gold-deep text-sm font-medium">Ir a Configuración →</Link>
          <button onClick={() => { agentsQ.refetch(); numbersQ.refetch() }} className="text-zinc-500 text-sm hover:text-zinc-700">Reintentar</button>
        </div>
      </Card>
    )
  }

  const agents = agentsQ.data || []
  const numbers = numbersQ.data || []
  // Sin esto, el botón queda clickeable con las listas vacías y dispara una
  // llamada al backend que ya sabemos que va a fallar (assistant_id/phone_id
  // undefined) — mejor no dejar iniciar la acción si falta configurar algo en Vapi.
  const missingSetup = !agents.length || !numbers.length

  const call = async () => {
    if (missingSetup) { setMsg({ ok: false, t: 'Configura al menos un agente y un número de origen en Vapi primero.' }); return }
    const d = digits.replace(/\D/g, '')
    if (d.length !== 9) { setMsg({ ok: false, t: 'Escribe los 9 dígitos (el 9 + 8 más).' }); return }
    setBusy(true); setMsg(null)
    try {
      await api.call({ number: '+56' + d, assistant_id: agent || agents[0]?.id, phone_number_id: num || numbers[0]?.id })
      setMsg({ ok: true, t: 'Llamada iniciada a +56' + d + '. Te debería sonar el teléfono.' })
    } catch (e) { setMsg({ ok: false, t: e.message }) } finally { setBusy(false) }
  }

  return (
    <motion.div initial="hidden" animate="show" variants={rise}>
      <Card className="p-6 max-w-xl space-y-4">
        <motion.div variants={fade}>
          <SectionTitle>Llamar con un agente</SectionTitle>
          <div className="text-sm text-zinc-500">Elegí el agente de voz y llamá. Probá con tu celular primero.</div>
        </motion.div>

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
          <Button variant="accent" onClick={call} disabled={busy || missingSetup}
                  title={missingSetup ? 'Configura un agente y un número de origen en Vapi primero' : undefined}>
            <Phone size={15} />{busy ? 'Llamando…' : 'Llamar'}
          </Button>
        </div>
      </div>

      {msg && <motion.div variants={fade} className={'text-sm ' + (msg.ok ? 'text-gold-deep' : 'text-rose-600')}>{msg.ok ? '✓ ' : ''}{msg.t}</motion.div>}
      </Card>
    </motion.div>
  )
}
