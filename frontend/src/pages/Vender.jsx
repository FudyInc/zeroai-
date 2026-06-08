import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Mail, Sparkles, Send } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { Card, Button, Input } from '../components/ui'

// Pon el mail de un prospecto → genera el pitch (editable) → envíalo por tu SMTP.
export default function Vender() {
  const { data: cfg } = useQuery({ queryKey: ['config'], queryFn: api.config })
  const [to, setTo] = useState('')
  const [name, setName] = useState('')
  const [company, setCompany] = useState('')
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)

  const generate = async () => {
    try {
      const p = await api.pitchCompose({ name, company })
      setSubject(p.subject); setBody(p.body)
    } catch (e) { toast.error('No se pudo generar: ' + e.message) }
  }

  const send = async () => {
    if (!to.trim()) return toast.error('Falta el correo del prospecto')
    if (!subject.trim() || !body.trim()) return toast.error('Genera o escribe el pitch primero')
    setBusy(true)
    try {
      await api.pitchSend({ to: to.trim(), subject, body })
      toast.success('Pitch enviado a ' + to.trim())
    } catch (e) { toast.error('No se pudo enviar: ' + e.message) }
    finally { setBusy(false) }
  }

  return (
    <div className="max-w-2xl space-y-4">
      {cfg && !cfg.email && (
        <Card className="p-4 border-amber-200 bg-amber-50/60 text-sm text-amber-800">
          Aún no conectas el email. Ve a <b>Configuración → Email (SMTP)</b> para poder enviar.
        </Card>
      )}

      <Card className="p-6 space-y-3">
        <div className="font-semibold flex items-center gap-2"><Mail size={16} /> A quién le escribes</div>
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="block text-xs text-zinc-500 mb-1">Correo del prospecto *</label>
            <Input type="email" value={to} onChange={(e) => setTo(e.target.value)} placeholder="contacto@empresa.com" />
          </div>
          <div>
            <label className="block text-xs text-zinc-500 mb-1">Nombre (opcional)</label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Diego" />
          </div>
          <div>
            <label className="block text-xs text-zinc-500 mb-1">Empresa (opcional)</label>
            <Input value={company} onChange={(e) => setCompany(e.target.value)} placeholder="Acme" />
          </div>
        </div>
        <Button variant="soft" onClick={generate}><Sparkles size={15} /> Generar pitch</Button>
      </Card>

      <Card className="p-6 space-y-3">
        <div className="font-semibold">El correo (edítalo antes de enviar)</div>
        <div>
          <label className="block text-xs text-zinc-500 mb-1">Asunto</label>
          <Input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Leads B2B calificados para tu empresa" />
        </div>
        <div>
          <label className="block text-xs text-zinc-500 mb-1">Mensaje</label>
          <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={14}
            placeholder="Pulsa 'Generar pitch' o escribe aquí…"
            className="w-full rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-emerald-500/30" />
        </div>
        <div className="flex justify-end">
          <Button variant="accent" onClick={send} disabled={busy}>
            <Send size={15} /> {busy ? 'Enviando…' : 'Enviar pitch'}
          </Button>
        </div>
      </Card>
    </div>
  )
}
