import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { CheckCircle2, AlertCircle, WifiOff } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { Card, Button, Input, Select, Skeleton, Badge, SectionTitle } from '../components/ui'
import AgentTester from '../components/AgentTester'
import { useApp } from '../App'
import { rise, fade, surface, stagger } from '../lib/motion'

export default function Config() {
  const { client } = useApp()
  const qc = useQueryClient()
  const { data: cfg, isLoading, error, refetch } = useQuery({ queryKey: ['config'], queryFn: api.config })
  const [vals, setVals] = useState({})
  const set = (k, v) => setVals((s) => ({ ...s, [k]: v }))

  const save = async (payload, clearKeys) => {
    try {
      const res = await api.setConfig(payload)
      setVals((s) => { const n = { ...s }; clearKeys.forEach((k) => delete n[k]); return n })
      qc.invalidateQueries({ queryKey: ['config'] })
      if (res?.backed_up) toast.success('Guardado y respaldado en la nube ✓ — sobrevive redeploys')
      else toast.warning('Guardado, pero SIN respaldo en la nube — conecta Supabase para que no se borre')
    } catch (e) { toast.error('No se pudo guardar: ' + e.message) }
  }

  if (isLoading) return <div className="max-w-xl space-y-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28 w-full" />)}</div>
  if (error) return <div className="max-w-xl py-16 text-center"><p className="text-rose-600">No se pudo cargar la configuración.</p><Button variant="soft" className="mt-3" onClick={() => refetch()}>Reintentar</Button></div>

  return (
    <motion.div className="max-w-xl space-y-4" initial="hidden" animate="show" variants={rise}>
      <motion.div variants={fade}>
        <CloudBackupBanner backedUp={cfg?.backed_up || []} supabase={cfg?.supabase} />
      </motion.div>

      <motion.div variants={surface}>
          <IntegrationCard title="Acceso (login de agencia)" ok={cfg?.auth} hint="protege el dashboard con una contraseña · vacío = abierto (solo local)">
          <div className="flex gap-2">
            <Input type="password" placeholder="Nueva contraseña" value={vals.pw || ''} onChange={(e) => set('pw', e.target.value)} />
            <Button onClick={() => vals.pw && save({ auth_password: vals.pw }, ['pw'])}>{cfg?.auth ? 'Cambiar' : 'Activar login'}</Button>
          </div>
        </IntegrationCard>
      </motion.div>

      <motion.div variants={surface}>
          <IntegrationCard title="ElevenLabs (voz)" ok={cfg?.elevenlabs} hint="se guarda en .env (local)">
          <div className="flex gap-2">
            <Input type="password" placeholder="sk_..." value={vals.el || ''} onChange={(e) => set('el', e.target.value)} />
            <Button onClick={() => vals.el && save({ elevenlabs_api_key: vals.el }, ['el'])}>Guardar</Button>
          </div>
        </IntegrationCard>
      </motion.div>

      <motion.div variants={surface}>
        <ClientChannelsCard key={client || 'sin-cliente'} client={client} />
      </motion.div>

      <motion.div variants={surface}>
          <IntegrationCard title="Supabase (datos en la nube · equipo)" ok={cfg?.supabase} hint="al conectarlo, el CRM pasa de archivos locales a Postgres compartido">
          <div className="space-y-2">
            <Input placeholder="Project URL (https://xxxx.supabase.co)" value={vals.su || ''} onChange={(e) => set('su', e.target.value)} />
            <Input type="password" placeholder="service_role key" value={vals.sk || ''} onChange={(e) => set('sk', e.target.value)} />
            <Button onClick={() => save({
              ...(vals.su && { supabase_url: vals.su }),
              ...(vals.sk && { supabase_key: vals.sk }),
            }, ['su', 'sk'])}>Conectar Supabase</Button>
          </div>
        </IntegrationCard>
      </motion.div>

      <motion.div variants={surface}>
        <IntegrationCard title="Anthropic (modo --live, opcional)" ok={cfg?.anthropic} hint="para correr el motor con Claude">
          <div className="flex gap-2">
            <Input type="password" placeholder="sk-ant-..." value={vals.an || ''} onChange={(e) => set('an', e.target.value)} />
            <Button onClick={() => vals.an && save({ anthropic_api_key: vals.an }, ['an'])}>Guardar</Button>
          </div>
        </IntegrationCard>
      </motion.div>

      <motion.div variants={surface}>
        <MetaAdsCard key={client || 'sin-cliente'} client={client} />
      </motion.div>

      <motion.div variants={fade}>
        <AgentTester />
      </motion.div>

      <motion.div variants={surface}>
        <Card className="p-6">
          <div className="flex items-center justify-between gap-4">
            <div>
              <SectionTitle className="flex items-center gap-2">
                Envío real
                {cfg?.outbox_live && (
                  <span className="text-sm text-gold-deep font-medium flex items-center gap-1">
                    <CheckCircle2 size={16} /> Activado
                  </span>
                )}
              </SectionTitle>
              <div className="text-xs text-zinc-400 mt-0.5">
                {cfg?.outbox_live
                  ? 'Los mensajes se ENVÍAN de verdad por los canales conectados.'
                  : 'Seguro: los mensajes se simulan (mock). Actívalo solo cuando quieras enviar de verdad.'}
              </div>
            </div>
            <Button variant={cfg?.outbox_live ? 'soft' : 'accent'}
              onClick={() => save({ outbox_live: !cfg?.outbox_live }, [])}>
              {cfg?.outbox_live ? 'Volver a mock' : 'Activar envío real'}
            </Button>
          </div>
        </Card>
      </motion.div>
    </motion.div>
  )
}

const CHANNEL_FIELDS = {
  email: [
    ['SMTP_HOST', 'Servidor SMTP'], ['SMTP_PORT', 'Puerto (587)'],
    ['SMTP_USER', 'Usuario'], ['SMTP_PASS', 'Contraseña', true], ['SMTP_FROM', 'Remitente (correo)'],
  ],
  vapi: [
    ['VAPI_API_KEY', 'API key de Vapi', true], ['VAPI_ASSISTANT_ID', 'Assistant ID (opcional)'],
    ['VAPI_PHONE_NUMBER_ID', 'Phone Number ID (opcional)'],
  ],
  whatsapp: [
    ['WHATSAPP_TOKEN', 'Token de WhatsApp Cloud', true], ['WHATSAPP_PHONE_ID', 'Phone Number ID'],
    ['WHATSAPP_VERIFY_TOKEN', 'Verify token del webhook', true],
    ['WHATSAPP_APP_SECRET', 'App Secret de Meta', true],
  ],
}

function ClientChannelsCard({ client }) {
  const qc = useQueryClient()
  const { data: status } = useQuery({ queryKey: ['integrations', client], queryFn: () => api.clientIntegrations(client), enabled: !!client })
  const [values, setValues] = useState({})
  const [busy, setBusy] = useState('')
  const save = async (channel) => {
    const fields = [...CHANNEL_FIELDS[channel].map(([key]) => key), ...(channel === 'whatsapp' ? ['WHATSAPP_PROVIDER'] : [])]
    const payload = Object.fromEntries(fields.filter((key) => values[key]?.trim()).map((key) => [key, values[key].trim()]))
    if (!client || !Object.keys(payload).length) return
    setBusy(channel)
    try {
      const result = await api.setClientIntegration(client, channel, payload)
      setValues((old) => Object.fromEntries(Object.entries(old).filter(([key]) => !fields.includes(key))))
      qc.invalidateQueries({ queryKey: ['integrations', client] })
      toast[result.backed_up ? 'success' : 'warning'](result.backed_up ? `Conexión de ${client} respaldada` : 'Guardado localmente; falta respaldo en la nube')
    } catch (error) { toast.error(error.message) }
    finally { setBusy('') }
  }
  return (
    <Card className="p-6 space-y-5">
      <div><SectionTitle>Integraciones de {client || 'un negocio'}</SectionTitle>
        <p className="text-xs text-zinc-500 mt-1">Estas credenciales solo se usan para el negocio seleccionado.</p></div>
      {Object.entries(CHANNEL_FIELDS).map(([channel, fields]) => (
        <div key={channel} className="border-t border-zinc-200 pt-4 space-y-2">
          <div className="flex justify-between items-center gap-2"><strong className="text-sm">{channel === 'email' ? 'Email SMTP' : channel === 'vapi' ? 'Llamadas Vapi' : 'WhatsApp Cloud API'}</strong>
            <Badge color={(channel === 'whatsapp' ? (status?.whatsapp_provider === 'web' ? status?.whatsapp_number : status?.whatsapp_cloud) : status?.[channel]) ? '#16a34a' : '#8C929B'}>{(channel === 'whatsapp' ? (status?.whatsapp_provider === 'web' ? status?.whatsapp_number : status?.whatsapp_cloud) : status?.[channel]) ? 'Configurado' : 'Sin conectar'}</Badge></div>
          {channel === 'whatsapp' && <Select aria-label="Proveedor de WhatsApp" value={values.WHATSAPP_PROVIDER || status?.whatsapp_provider || 'meta'} onChange={(event) => setValues((old) => ({ ...old, WHATSAPP_PROVIDER: event.target.value }))} disabled={!client || !!busy}>
            <option value="web">WhatsApp Web (sesión propia)</option><option value="meta">Meta Cloud API</option>
          </Select>}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {fields.map(([key, label, secret]) => <Input key={key} type={secret ? 'password' : 'text'} autoComplete="off" aria-label={label} placeholder={label} value={values[key] || ''} onChange={(event) => setValues((old) => ({ ...old, [key]: event.target.value }))} disabled={!client || !!busy} />)}
          </div>
          <Button variant="soft" onClick={() => save(channel)} disabled={!client || !!busy}>Guardar {channel}</Button>
          {channel === 'email' && status?.email && <TestEmailRow client={client} />}
        </div>
      ))}
      <p className="text-xs text-zinc-500">WhatsApp Web se vincula por negocio desde la sección WhatsApp.</p>
    </Card>
  )
}

/* El token pertenece al negocio seleccionado. La cuenta se asigna en Campañas. */
function MetaAdsCard({ client }) {
  const qc = useQueryClient()
  const { data: marketing, isError } = useQuery({
    queryKey: ['marketing', client], queryFn: () => api.marketing(client), enabled: !!client,
  })
  const [token, setToken] = useState('')
  const [probe, setProbe] = useState(null)
  const [busy, setBusy] = useState(false)
  const connected = !!marketing?.metaads_connected
  const status = probe?.ok === false
    ? { label: 'Error de acceso', color: '#e11d48', icon: AlertCircle }
    : connected
      ? { label: 'Configurado', color: '#16a34a', icon: CheckCircle2 }
      : { label: 'Sin conectar', color: '#8C929B', icon: WifiOff }

  const testConnection = async () => {
    setBusy(true)
    try {
      const accounts = await api.metaadsAccounts(client)
      setProbe({ ok: true, accounts })
      toast.success('Conexión con Meta OK')
    } catch (e) {
      setProbe({ ok: false, error: e.message })
      toast.error('Conexión falló: ' + e.message)
    } finally { setBusy(false) }
  }

  const connect = async () => {
    if (!client || !token.trim()) return
    setBusy(true)
    try {
      const saved = await api.setMetaadsToken(client, token.trim())
      setToken('')
      setProbe(null)
      await qc.invalidateQueries({ queryKey: ['marketing', client] })
      if (saved.backed_up) toast.success(`Token de Meta Ads guardado para ${client}`)
      else toast.warning('Token guardado localmente; no se pudo respaldar en la nube')
    } catch (e) { toast.error('No se pudo guardar: ' + e.message) }
    finally { setBusy(false) }
  }

  return (
    <Card className="p-6">
      <div className="flex items-center justify-between">
        <SectionTitle>Meta Ads · {client || 'elige un negocio'}</SectionTitle>
        <Badge color={status.color} className="inline-flex items-center gap-1">
          <status.icon size={12} /> {status.label}
        </Badge>
      </div>
      <p className="text-xs text-zinc-500 mt-1 mb-3">La credencial se guarda solo para este negocio. La cuenta publicitaria se asigna en <Link to="/campanas" className="text-gold-deep underline">Campañas</Link>.</p>
      {isError && <p className="text-xs text-rose-600 mb-2">No se pudo leer la configuración de este negocio.</p>}
      {marketing?.config?.ad_account && <p className="text-xs text-zinc-500 mb-3">Cuenta asignada: <code>{marketing.config.ad_account}</code></p>}

      {probe?.ok === false && (
        <div className="text-xs text-rose-600 mb-2 break-words">{probe.error}</div>
      )}

      <div className="space-y-2">
        <Input type="password" autoComplete="off" aria-label="Token Meta Ads del negocio" placeholder="Access token para este negocio" value={token} onChange={(e) => setToken(e.target.value)} disabled={!client || busy} />
        <div className="flex flex-wrap gap-2">
          <Button onClick={connect} disabled={!client || !token.trim() || busy}>Guardar token</Button>
          <Button variant="soft" onClick={testConnection} disabled={!client || busy}>{busy ? 'Probando…' : 'Probar conexión'}</Button>
        </div>
      </div>

      {probe?.ok && (
        <div className="mt-3 space-y-1">
          {probe.accounts.length === 0 && <div className="text-xs text-zinc-400">El token no ve cuentas publicitarias.</div>}
          {probe.accounts.map((a) => (
            <div key={a.id} className="text-xs flex items-center gap-2 bg-zinc-50 dark:bg-zinc-100 rounded-lg px-2 py-1">
              <code className="text-gold-deep font-semibold">{a.id}</code>
              <span className="text-zinc-500">{a.name}</span>
            </div>
          ))}
          {probe.accounts.length > 0 && <div className="text-[11px] text-zinc-500 mt-1">Asigna el <code>act_…</code> correspondiente en Campañas → Config del cliente.</div>}
        </div>
      )}
    </Card>
  )
}

/* Manda un correo de prueba a tu propia dirección para verificar que el SMTP envía. */
function TestEmailRow({ client }) {
  const [to, setTo] = useState('')
  const [busy, setBusy] = useState(false)
  const send = async () => {
    if (!to.trim()) return
    setBusy(true)
    try {
      await api.testEmail(client, to.trim())
      toast.success('Correo de prueba enviado — revisa tu inbox (y spam)')
    } catch (e) { toast.error('No se pudo enviar: ' + e.message) }
    finally { setBusy(false) }
  }
  return (
    <Card className="p-4 -mt-2 border-dashed">
      <div className="text-xs text-zinc-500 mb-2">Probar envío — te llega un correo a esta dirección</div>
      <div className="flex gap-2">
        <Input type="email" placeholder="tu-correo@gmail.com" value={to} onChange={(e) => setTo(e.target.value)} />
        <Button variant="soft" onClick={send} disabled={busy}>{busy ? 'Enviando…' : 'Probar envío'}</Button>
      </div>
    </Card>
  )
}

/* Aviso de blindaje: muestra qué keys están respaldadas en la nube (sobreviven
   a redeploys) para que el usuario tenga certeza de que no se borrarán. */
const _NAMES = {
  VAPI: 'Vapi', SMTP: 'Email', ELEVENLABS: 'ElevenLabs', META: 'Meta Ads',
  WHATSAPP: 'WhatsApp', ANTHROPIC: 'Anthropic', AUTH: 'Login', OUTBOX: 'Envío real', SUPABASE: 'Supabase',
}
function CloudBackupBanner({ backedUp, supabase }) {
  const names = [...new Set(backedUp.map((k) => _NAMES[k.split('_')[0]] || k))]
  if (!supabase) return (
    <Card className="p-4 border-amber-200 bg-amber-50/70 text-sm text-amber-800">
      ⚠️ <b>Sin Supabase conectado, las keys no se respaldan</b> y se borran en cada redeploy. Conéctalo abajo (tarjeta Supabase) para protegerlas.
    </Card>
  )
  if (names.length === 0) return (
    <Card className="p-4 border-zinc-200 bg-zinc-50 text-sm text-zinc-600">
      🔒 Las keys que guardes aquí quedan <b>respaldadas en la nube</b> y sobreviven a los redeploys. Aún no hay ninguna guardada.
    </Card>
  )
  return (
    <Card className="p-4 border-champagne bg-champagne/30 text-sm text-brand">
      🔒 <b>Respaldado en la nube — sobrevive a cualquier redeploy.</b>
      <div className="text-xs text-gold-deep mt-1">Protegido: {names.join(' · ')}</div>
    </Card>
  )
}

/* Si ya está conectado, se colapsa a "Conectado ✓" y oculta el input
   (con opción de reconfigurar). Si no, muestra los campos. */
function IntegrationCard({ title, ok, hint, children }) {
  const [editing, setEditing] = useState(false)
  return (
    <Card className="p-6">
      <div className="flex items-center justify-between">
        <SectionTitle>{title}</SectionTitle>
        {ok && (
          <span className="text-sm text-gold-deep font-medium flex items-center gap-1">
            <CheckCircle2 size={16} /> Conectado
          </span>
        )}
      </div>
      {ok && !editing ? (
        <div className="text-xs text-zinc-400 mt-1">
          Listo, no hay nada que hacer.{' '}
          <button onClick={() => setEditing(true)} className="text-gold-deep hover:underline">Reconfigurar</button>
        </div>
      ) : (
        <>
          {hint && <div className="text-xs text-zinc-400 mt-0.5 mb-3">{hint}</div>}
          {children}
        </>
      )}
    </Card>
  )
}
