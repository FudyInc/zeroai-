import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Mail, Phone, MessageCircle, Instagram, Linkedin, Clock } from 'lucide-react'
import { api } from '../lib/api'
import { repliedRecently } from '../lib/util'
import { Card } from '../components/ui'
import { useApp } from '../App'

/* Vista general de los canales de contacto — el punto de entrada para elegir
   por dónde llega el agente al lead. La configuración a fondo del agente de
   WhatsApp (ficha de la empresa, precios, quién atiende, desplegar) vive
   DENTRO de la card de WhatsApp de abajo — es 100% específica de ese canal
   (el único con conversación de ida y vuelta hoy), no de "agentes" en
   general, así que no tiene sentido como paso genérico acá. */

const TONES = {
  ok: 'text-gold-deep bg-champagne/30',
  warn: 'text-amber-700 bg-amber-50',
  soon: 'text-pewter bg-pewter/10',
  bad: 'text-rose-600 bg-rose-50',
}

export default function Agentes() {
  const { client } = useApp()
  const cfgQ = useQuery({ queryKey: ['config'], queryFn: api.config })
  const cfg = cfgQ.data
  const leadsQ = useQuery({
    queryKey: ['leads', client, 'agentes-activity'],
    queryFn: () => api.leads(client, { group: 'todos', limit: 50 }),
    enabled: !!client,
  })
  const nav = useNavigate()

  const leadRows = leadsQ.data?.leads
  const emailReplied = repliedRecently(leadRows, 'email')
  const waReplied = repliedRecently(leadRows, 'whatsapp')
  const activityLine = (n) => n != null && n > 0
    ? `${n} ${n === 1 ? 'lead respondió' : 'leads respondieron'} en 24h`
    : null

  const agents = [
    {
      key: 'email', name: 'Email', icon: Mail, chip: 'bg-brand/8 text-brand',
      desc: 'Envía un pitch con demo a un prospecto y los seguimientos por correo.',
      status: cfg?.email ? { t: 'Conectado', tone: 'ok' } : { t: 'Configurar', tone: 'warn' },
      onClick: () => nav(cfg?.email ? '/vender' : '/config'),
      activity: activityLine(emailReplied),
    },
    {
      key: 'call', name: 'Llamadas', icon: Phone, chip: 'bg-champagne/35 text-gold-deep',
      desc: 'Llama con un agente de voz (Fernanda) por teléfono.',
      status: cfg?.vapi ? { t: 'Activo', tone: 'ok' } : { t: 'Configurar', tone: 'warn' },
      onClick: () => nav('/llamadas'),
      activity: null,
    },
    {
      key: 'wa', name: 'WhatsApp', icon: MessageCircle, chip: 'bg-gold/15 text-gold-deep',
      desc: 'Configura la ficha, quién atiende y prueba el agente que responde dudas y agenda (ventana de 24h).',
      status: cfg?.whatsapp ? { t: 'Activo', tone: 'ok' } : { t: 'Configurar / probar', tone: 'warn' },
      onClick: () => nav('/whatsapp'),
      activity: activityLine(waReplied),
    },
    {
      key: 'ig', name: 'Instagram', icon: Instagram, chip: 'bg-pewter/15 text-pewter',
      desc: 'DMs en frío: la plataforma los bloquea (sin API oficial).',
      status: { t: 'No viable (ToS)', tone: 'bad' },
      onClick: null, disabled: true, activity: null,
    },
    {
      key: 'li', name: 'LinkedIn', icon: Linkedin, chip: 'bg-pewter/15 text-pewter',
      desc: 'Automatizar mensajes rompe sus términos (riesgo de baneo).',
      status: { t: 'No viable (ToS)', tone: 'bad' },
      onClick: null, disabled: true, activity: null,
    },
  ]

  return (
    <div className="space-y-4">
      <p className="text-sm text-zinc-500 max-w-2xl">
        Un agente por canal, todos con el mismo cerebro — cambia solo la forma de llegar al prospecto.
        Elige uno para configurarlo o ver su estado.
      </p>
      {cfgQ.isError && (
        <Card className="p-4 text-sm text-rose-600">
          No se pudo cargar el estado real de los canales (se muestran como "sin configurar" por
          defecto, puede no ser cierto). <button className="underline" onClick={() => cfgQ.refetch()}>Reintentar</button>
        </Card>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {agents.map((a, i) => (
          <motion.div key={a.key} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
            <Card
              interactive={!a.disabled && !!a.onClick}
              onClick={a.disabled ? undefined : a.onClick}
              className={'p-5 h-full ' + (a.disabled ? 'opacity-60' : a.onClick ? 'cursor-pointer' : '')}
            >
              <div className="flex items-start justify-between">
                <div className={'w-11 h-11 rounded-xl grid place-items-center ' + a.chip}>
                  <a.icon size={20} />
                </div>
                <span className={'text-xs font-medium px-2 py-1 rounded-full ' + TONES[a.status.tone]}>{a.status.t}</span>
              </div>
              <div className="font-display font-bold tracking-tight text-brand mt-3">{a.name}</div>
              <div className="text-sm text-zinc-500 mt-1">{a.desc}</div>
              {a.activity && (
                <div className="flex items-center gap-1.5 text-xs font-medium text-gold-deep mt-3 pt-3 border-t border-zinc-100">
                  <Clock size={12} />{a.activity}
                </div>
              )}
            </Card>
          </motion.div>
        ))}
      </div>
    </div>
  )
}
