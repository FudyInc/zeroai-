import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2 } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { Card, Button, Input, Skeleton } from '../components/ui'

export default function Config() {
  const qc = useQueryClient()
  const { data: cfg, isLoading, error, refetch } = useQuery({ queryKey: ['config'], queryFn: api.config })
  const [vals, setVals] = useState({})
  const set = (k, v) => setVals((s) => ({ ...s, [k]: v }))

  const save = async (payload, clearKeys) => {
    try {
      await api.setConfig(payload)
      setVals((s) => { const n = { ...s }; clearKeys.forEach((k) => delete n[k]); return n })
      qc.invalidateQueries({ queryKey: ['config'] })
      toast.success('Conexión guardada')
    } catch (e) { toast.error('No se pudo guardar: ' + e.message) }
  }

  if (isLoading) return <div className="max-w-xl space-y-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28 w-full" />)}</div>
  if (error) return <div className="max-w-xl py-16 text-center"><p className="text-rose-600">No se pudo cargar la configuración.</p><Button variant="soft" className="mt-3" onClick={() => refetch()}>Reintentar</Button></div>

  return (
    <div className="max-w-xl space-y-4">
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
    </div>
  )
}

/* Si ya está conectado, se colapsa a "Conectado ✓" y oculta el input
   (con opción de reconfigurar). Si no, muestra los campos. */
function IntegrationCard({ title, ok, hint, children }) {
  const [editing, setEditing] = useState(false)
  return (
    <Card className="p-6">
      <div className="flex items-center justify-between">
        <div className="font-semibold">{title}</div>
        {ok && (
          <span className="text-sm text-emerald-600 font-medium flex items-center gap-1">
            <CheckCircle2 size={16} /> Conectado
          </span>
        )}
      </div>
      {ok && !editing ? (
        <div className="text-xs text-zinc-400 mt-1">
          Listo, no hay nada que hacer.{' '}
          <button onClick={() => setEditing(true)} className="text-emerald-700 hover:underline">Reconfigurar</button>
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
