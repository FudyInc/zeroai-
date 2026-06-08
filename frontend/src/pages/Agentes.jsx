import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Mail, Phone, MessageCircle, Instagram, Linkedin } from 'lucide-react'
import { api } from '../lib/api'
import { Card } from '../components/ui'

const TONES = {
  ok: 'text-emerald-700 bg-emerald-50',
  warn: 'text-amber-700 bg-amber-50',
  soon: 'text-zinc-500 bg-zinc-100',
  bad: 'text-rose-600 bg-rose-50',
}

export default function Agentes() {
  const { data: cfg } = useQuery({ queryKey: ['config'], queryFn: api.config })
  const nav = useNavigate()

  const agents = [
    {
      key: 'email', name: 'Email', icon: Mail, bg: '#eef2ff', fg: '#6366f1',
      desc: 'Envía un pitch con demo a un prospecto y los seguimientos por correo.',
      status: cfg?.email ? { t: 'Conectado', tone: 'ok' } : { t: 'Configurar', tone: 'warn' },
      onClick: () => nav(cfg?.email ? '/vender' : '/config'),
    },
    {
      key: 'call', name: 'Llamadas', icon: Phone, bg: '#ecfdf5', fg: '#10b981',
      desc: 'Llama con un agente de voz (Fernanda) por teléfono.',
      status: cfg?.vapi ? { t: 'Activo', tone: 'ok' } : { t: 'Configurar', tone: 'warn' },
      onClick: () => nav('/llamadas'),
    },
    {
      key: 'wa', name: 'WhatsApp', icon: MessageCircle, bg: '#f0fdf4', fg: '#16a34a',
      desc: 'Agente que responde dudas del lead y agenda (ventana de 24h).',
      status: cfg?.whatsapp ? { t: 'Activo', tone: 'ok' } : { t: 'Configurar / probar', tone: 'warn' },
      onClick: () => nav('/config'),
    },
    {
      key: 'ig', name: 'Instagram', icon: Instagram, bg: '#fdf2f8', fg: '#db2777',
      desc: 'DMs en frío: la plataforma los bloquea (sin API oficial).',
      status: { t: 'No viable (ToS)', tone: 'bad' },
      onClick: null, disabled: true,
    },
    {
      key: 'li', name: 'LinkedIn', icon: Linkedin, bg: '#eff6ff', fg: '#2563eb',
      desc: 'Automatizar mensajes rompe sus términos (riesgo de baneo).',
      status: { t: 'No viable (ToS)', tone: 'bad' },
      onClick: null, disabled: true,
    },
  ]

  return (
    <div className="space-y-5">
      <p className="text-sm text-zinc-500 max-w-2xl">
        Un agente por canal. Cada uno usa el mismo cerebro de ZeroAI (descubre → califica → contacta),
        cambiando solo la forma de llegar al prospecto. Mostramos cada canal con su estado real.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {agents.map((a, i) => (
          <motion.div key={a.key} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
            <Card
              interactive={!a.disabled && !!a.onClick}
              onClick={a.disabled ? undefined : a.onClick}
              className={'p-5 h-full ' + (a.disabled ? 'opacity-60' : a.onClick ? 'cursor-pointer' : '')}
            >
              <div className="flex items-start justify-between">
                <div className="w-11 h-11 rounded-xl grid place-items-center" style={{ background: a.bg, color: a.fg }}>
                  <a.icon size={20} />
                </div>
                <span className={'text-xs font-medium px-2 py-1 rounded-full ' + TONES[a.status.tone]}>{a.status.t}</span>
              </div>
              <div className="font-semibold mt-3">{a.name}</div>
              <div className="text-sm text-zinc-500 mt-1">{a.desc}</div>
            </Card>
          </motion.div>
        ))}
      </div>
    </div>
  )
}
