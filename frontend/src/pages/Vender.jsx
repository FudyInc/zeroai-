import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { Mail, Sparkles, Send } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { Card, Button, Input, Badge, SectionTitle } from '../components/ui'
import { Glow } from '../components/Glow'
import { rise, fade, surface } from '../lib/motion'

// Pon el mail de un prospecto → genera el pitch (editable) → envíalo por tu SMTP.
export default function Vender() {
  const { data: cfg } = useQuery({ queryKey: ['config'], queryFn: api.config })
  const { data: emails = [] } = useQuery({ queryKey: ['usedEmails'], queryFn: api.usedEmails })
  const qc = useQueryClient()
  const [to, setTo] = useState('')
  const [name, setName] = useState('')
  const [company, setCompany] = useState('')
  const [notes, setNotes] = useState('')
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)
  const [genBusy, setGenBusy] = useState(false)
  const [mode, setMode] = useState(null)

  const generate = async () => {
    setGenBusy(true)
    try {
      const p = await api.pitchGenerate({ name, company, notes })
      setSubject(p.subject); setBody(p.body); setMode(p.mode)
    } catch (e) { toast.error('No se pudo generar: ' + e.message) }
    finally { setGenBusy(false) }
  }

  const send = async () => {
    if (!to.trim()) return toast.error('Falta el correo del prospecto')
    if (!subject.trim() || !body.trim()) return toast.error('Genera o escribe el pitch primero')
    setBusy(true)
    try {
      await api.pitchSend({ to: to.trim(), subject, body })
      toast.success('Pitch enviado a ' + to.trim())
      qc.invalidateQueries({ queryKey: ['usedEmails'] })
    } catch (e) { toast.error('No se pudo enviar: ' + e.message) }
    finally { setBusy(false) }
  }

  return (
    <motion.div className="max-w-2xl space-y-4" initial="hidden" animate="show" variants={rise}>
      {cfg && !cfg.email && (
        <motion.div variants={fade}>
          <Card className="p-4 border-amber-200 bg-amber-50/60 text-sm text-amber-800">
            Aún no conectas el email. Ve a <b>Configuración → Email (SMTP)</b> para poder enviar.
          </Card>
        </motion.div>
      )}

      <motion.div variants={surface}>
        <Card className="p-6 space-y-3">
        <SectionTitle className="flex items-center gap-2"><Mail size={16} /> A quién le escribes</SectionTitle>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="sm:col-span-2">
            <label className="block text-xs text-zinc-500 mb-1">Correo del prospecto *</label>
            <Input type="email" list="used-emails" value={to} onChange={(e) => setTo(e.target.value)} placeholder="contacto@empresa.com" />
            <datalist id="used-emails">
              {emails.map((e) => <option key={e} value={e} />)}
            </datalist>
          </div>
          <div>
            <label className="block text-xs text-zinc-500 mb-1">Nombre (opcional)</label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Diego" />
          </div>
          <div>
            <label className="block text-xs text-zinc-500 mb-1">Empresa (opcional)</label>
            <Input value={company} onChange={(e) => setCompany(e.target.value)} placeholder="Acme" />
          </div>
          <div className="sm:col-span-2">
            <label className="block text-xs text-zinc-500 mb-1">Contexto / ángulo (opcional) — qué sabes del prospecto, qué tono</label>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3}
              placeholder="Ej: agencia de marketing en Providencia, vi su web nueva; tono cercano y directo."
              className="w-full rounded-xl border border-zinc-200 bg-white dark:bg-[#1D2016] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gold/40" />
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Button variant="accent" onClick={generate} disabled={genBusy}>
            <Sparkles size={15} /> {genBusy ? 'Escribiendo…' : (subject ? 'Regenerar con IA' : 'Generar con IA')}
          </Button>
          {mode && <Badge color={mode === 'live' ? '#16a34a' : '#94a3b8'}>{mode === 'live' ? 'IA real' : 'mock (varía)'}</Badge>}
          <span className="text-xs text-zinc-400">Cada generación es distinta — con modelo (Anthropic o local) es de verdad creativa.</span>
        </div>
        </Card>
      </motion.div>

      <motion.div variants={surface}>
        <Card className="p-6 space-y-3">
          <SectionTitle>El correo (edítalo antes de enviar)</SectionTitle>
        <div>
          <label className="block text-xs text-zinc-500 mb-1">Asunto</label>
          <Input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Leads B2B calificados para tu empresa" />
        </div>
        <div>
          <label className="block text-xs text-zinc-500 mb-1">Mensaje</label>
          <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={14}
            placeholder="Pulsa 'Generar pitch' o escribe aquí…"
            className="w-full rounded-xl border border-zinc-200 bg-white dark:bg-[#1D2016] px-3 py-2 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-gold/40" />
        </div>
        <div className="flex justify-end">
          <Glow>
            <Button variant="accent" onClick={send} disabled={busy}>
              <Send size={15} /> {busy ? 'Enviando…' : 'Enviar pitch'}
            </Button>
          </Glow>
        </div>
        </Card>
      </motion.div>
    </motion.div>
  )
}
