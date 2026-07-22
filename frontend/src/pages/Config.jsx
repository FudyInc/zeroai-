import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, AlertCircle, WifiOff } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { Card, Button, Input, Skeleton, Badge, SectionTitle } from '../components/ui'
import AgentTester from '../components/AgentTester'

export default function Config() {
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
    <div className="max-w-xl space-y-4">
      <CloudBackupBanner backedUp={cfg?.backed_up || []} supabase={cfg?.supabase} />

      <IntegrationCard title="Acceso (login de agencia)" ok={cfg?.auth} hint="protege el dashboard con una contraseña · vacío = abierto (solo local)">
        <div className="flex gap-2">
          <Input type="password" placeholder="Nueva contraseña" value={vals.pw || ''} onChange={(e) => set('pw', e.target.value)} />
          <Button onClick={() => vals.pw && save({ auth_password: vals.pw }, ['pw'])}>{cfg?.auth ? 'Cambiar' : 'Activar login'}</Button>
        </div>
      </IntegrationCard>

      <IntegrationCard title="ElevenLabs (voz)" ok={cfg?.elevenlabs} hint="se guarda en .env (local)">
        <div className="flex gap-2">
          <Input type="password" placeholder="sk_..." value={vals.el || ''} onChange={(e) => set('el', e.target.value)} />
          <Button onClick={() => vals.el && save({ elevenlabs_api_key: vals.el }, ['el'])}>Guardar</Button>
        </div>
      </IntegrationCard>

      <IntegrationCard title="Vapi (llamadas)" ok={cfg?.vapi} hint="con tu API key se listan agentes y números solos">
        <div className="space-y-2">
          <Input type="password" placeholder="Vapi API key" value={vals.vk || ''} onChange={(e) => set('vk', e.target.value)} />
          <Input placeholder="Assistant ID (opcional)" value={vals.va || ''} onChange={(e) => set('va', e.target.value)} />
          <Input placeholder="Phone Number ID (opcional)" value={vals.vp || ''} onChange={(e) => set('vp', e.target.value)} />
          <Button onClick={() => save({
            ...(vals.vk && { vapi_api_key: vals.vk }),
            ...(vals.va && { vapi_assistant_id: vals.va }),
            ...(vals.vp && { vapi_phone_number_id: vals.vp }),
          }, ['vk', 'va', 'vp'])}>Guardar Vapi</Button>
        </div>
      </IntegrationCard>

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

      <IntegrationCard title="Anthropic (modo --live, opcional)" ok={cfg?.anthropic} hint="para correr el motor con Claude">
        <div className="flex gap-2">
          <Input type="password" placeholder="sk-ant-..." value={vals.an || ''} onChange={(e) => set('an', e.target.value)} />
          <Button onClick={() => vals.an && save({ anthropic_api_key: vals.an }, ['an'])}>Guardar</Button>
        </div>
      </IntegrationCard>

      <div className="pt-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">Canales de envío</div>

      <IntegrationCard title="Email (SMTP · email marketing)" ok={cfg?.email} hint="con esto el primer toque y los follow-ups salen por correo de verdad">
        <div className="space-y-2">
          <Input placeholder="SMTP host (smtp.gmail.com)" value={vals.sh || ''} onChange={(e) => set('sh', e.target.value)} />
          <div className="flex gap-2">
            <Input placeholder="Puerto (587)" value={vals.sp || ''} onChange={(e) => set('sp', e.target.value)} className="w-28" />
            <Input placeholder="From (hola@tudominio.com)" value={vals.sfrom || ''} onChange={(e) => set('sfrom', e.target.value)} />
          </div>
          <Input placeholder="Usuario" value={vals.suser || ''} onChange={(e) => set('suser', e.target.value)} />
          <Input type="password" placeholder="Contraseña / app password" value={vals.spass || ''} onChange={(e) => set('spass', e.target.value)} />
          <Button onClick={() => save({
            ...(vals.sh && { smtp_host: vals.sh }),
            ...(vals.sp && { smtp_port: vals.sp }),
            ...(vals.sfrom && { smtp_from: vals.sfrom }),
            ...(vals.suser && { smtp_user: vals.suser }),
            ...(vals.spass && { smtp_pass: vals.spass }),
          }, ['sh', 'sp', 'sfrom', 'suser', 'spass'])}>Guardar SMTP</Button>
        </div>
      </IntegrationCard>

      {cfg?.email && <TestEmailRow />}

      <IntegrationCard title="WhatsApp (Meta Cloud API)" ok={cfg?.whatsapp} hint="token + phone number ID de tu app de WhatsApp Business · el agente responde dentro de la ventana de 24h">
        <div className="space-y-2">
          <Input type="password" placeholder="WhatsApp token" value={vals.wt || ''} onChange={(e) => set('wt', e.target.value)} />
          <Input placeholder="Phone Number ID" value={vals.wp || ''} onChange={(e) => set('wp', e.target.value)} />
          <Input placeholder="Verify token (lo inventas tú, p/ el webhook)" value={vals.wv || ''} onChange={(e) => set('wv', e.target.value)} />
          <Input type="password" placeholder="App Secret (Meta Business Settings → App → Basic)" value={vals.was || ''} onChange={(e) => set('was', e.target.value)} />
          <Button onClick={() => save({
            ...(vals.wt && { whatsapp_token: vals.wt }),
            ...(vals.wp && { whatsapp_phone_id: vals.wp }),
            ...(vals.wv && { whatsapp_verify_token: vals.wv }),
            ...(vals.was && { whatsapp_app_secret: vals.was }),
          }, ['wt', 'wp', 'wv', 'was'])}>Guardar WhatsApp</Button>
        </div>
      </IntegrationCard>

      <MetaAdsCard cfg={cfg} vals={vals} set={set} save={save} />

      <AgentTester />

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
    </div>
  )
}

/* Tarjeta de Meta Ads en Config: estado de conexión (Conectado / Error / Sin conectar),
   campos para token + cuenta, y botón "Probar conexión" que lista las cuentas
   publicitarias visibles para ese token (para elegir el act_ correcto). */
function MetaAdsCard({ cfg, vals, set, save }) {
  const [editing, setEditing] = useState(false)
  const [probe, setProbe] = useState(null) // null | { ok: true, accounts } | { ok: false, error }
  const [busy, setBusy] = useState(false)

  const connected = !!cfg?.metaads
  const status = probe?.ok === false
    ? { label: 'Error: Key inválida', color: '#e11d48', icon: AlertCircle }
    : connected
      ? { label: 'Conectado', color: '#16a34a', icon: CheckCircle2 }
      : { label: 'Sin conectar', color: '#8C929B', icon: WifiOff }

  const testConnection = async () => {
    setBusy(true)
    try {
      const accounts = await api.metaadsAccounts()
      setProbe({ ok: true, accounts })
      toast.success('Conexión con Meta OK')
    } catch (e) {
      setProbe({ ok: false, error: e.message })
      toast.error('Conexión falló: ' + e.message)
    } finally { setBusy(false) }
  }

  const connect = () => {
    save({
      ...(vals.mt && { meta_ads_token: vals.mt }),
      ...(vals.ma && { meta_ad_account_id: vals.ma }),
    }, ['mt', 'ma'])
    setEditing(false)
    setProbe(null)
  }

  return (
    <Card className="p-6">
      <div className="flex items-center justify-between">
        <SectionTitle>Meta Ads (campañas)</SectionTitle>
        <Badge color={status.color} className="inline-flex items-center gap-1">
          <status.icon size={12} /> {status.label}
        </Badge>
      </div>
      <div className="text-xs text-zinc-400 mt-0.5 mb-3">
        access token + Ad Account ID (act_…) de tu Meta Business · sin esto, datos mock
      </div>

      {probe?.ok === false && (
        <div className="text-xs text-rose-600 mb-2 break-words">{probe.error}</div>
      )}

      {connected && !editing ? (
        <div className="flex items-center gap-2">
          <Button variant="soft" onClick={testConnection} disabled={busy}>
            {busy ? 'Probando…' : 'Probar conexión'}
          </Button>
          <Button variant="ghost" onClick={() => setEditing(true)}>Reconectar</Button>
        </div>
      ) : (
        <div className="space-y-2">
          <Input type="password" placeholder="Access token" value={vals.mt || ''} onChange={(e) => set('mt', e.target.value)} />
          <Input placeholder="Ad Account ID (act_123…)" value={vals.ma || ''} onChange={(e) => set('ma', e.target.value)} />
          <div className="flex gap-2">
            <Button onClick={connect}>{connected ? 'Guardar y reconectar' : 'Conectar Meta Ads'}</Button>
            {connected && <Button variant="ghost" onClick={() => setEditing(false)}>Cancelar</Button>}
          </div>
        </div>
      )}

      {probe?.ok && (
        <div className="mt-3 space-y-1">
          {probe.accounts.length === 0 && <div className="text-xs text-zinc-400">El token no ve cuentas publicitarias.</div>}
          {probe.accounts.map((a) => (
            <div key={a.id} className="text-xs flex items-center gap-2 bg-zinc-50 rounded-lg px-2 py-1">
              <code className="text-gold-deep font-semibold">{a.id}</code>
              <span className="text-zinc-500">{a.name}</span>
            </div>
          ))}
          {probe.accounts.length > 0 && <div className="text-[11px] text-zinc-400 mt-1">Copia el <code>act_…</code> de la cuenta que quieras al campo de arriba y guarda.</div>}
        </div>
      )}
    </Card>
  )
}

/* Manda un correo de prueba a tu propia dirección para verificar que el SMTP envía. */
function TestEmailRow() {
  const [to, setTo] = useState('')
  const [busy, setBusy] = useState(false)
  const send = async () => {
    if (!to.trim()) return
    setBusy(true)
    try {
      await api.testEmail(to.trim())
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
