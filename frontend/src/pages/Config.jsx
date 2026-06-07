import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { Card, Button, Input } from '../components/ui'

function Status({ ok }) {
  return ok
    ? <span className="text-emerald-600 font-medium">configurada ✓</span>
    : <span className="text-zinc-400">no configurada</span>
}

export default function Config() {
  const qc = useQueryClient()
  const { data: cfg } = useQuery({ queryKey: ['config'], queryFn: api.config })
  const [vals, setVals] = useState({})
  const set = (k, v) => setVals((s) => ({ ...s, [k]: v }))

  const save = async (payload, clearKeys) => {
    await api.setConfig(payload)
    setVals((s) => { const n = { ...s }; clearKeys.forEach((k) => delete n[k]); return n })
    qc.invalidateQueries({ queryKey: ['config'] })
  }

  return (
    <div className="max-w-xl space-y-4">
      <Card className="p-6">
        <div className="font-semibold">ElevenLabs (voz)</div>
        <div className="text-xs text-zinc-400 mt-0.5 mb-3">Estado: <Status ok={cfg?.elevenlabs} /> · se guarda en .env (local)</div>
        <div className="flex gap-2">
          <Input type="password" placeholder="sk_..." value={vals.el || ''} onChange={(e) => set('el', e.target.value)} />
          <Button onClick={() => vals.el && save({ elevenlabs_api_key: vals.el }, ['el'])}>Guardar</Button>
        </div>
      </Card>

      <Card className="p-6">
        <div className="font-semibold">Vapi (llamadas)</div>
        <div className="text-xs text-zinc-400 mt-0.5 mb-3">Estado: <Status ok={cfg?.vapi} /> · con tu API key se listan agentes y números solos</div>
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
      </Card>

      <Card className="p-6">
        <div className="font-semibold">Supabase (datos en la nube · equipo)</div>
        <div className="text-xs text-zinc-400 mt-0.5 mb-3">Estado: <Status ok={cfg?.supabase} /> · al conectarlo, el CRM pasa de archivos locales a Postgres compartido</div>
        <div className="space-y-2">
          <Input placeholder="Project URL (https://xxxx.supabase.co)" value={vals.su || ''} onChange={(e) => set('su', e.target.value)} />
          <Input type="password" placeholder="service_role key" value={vals.sk || ''} onChange={(e) => set('sk', e.target.value)} />
          <Button onClick={() => save({
            ...(vals.su && { supabase_url: vals.su }),
            ...(vals.sk && { supabase_key: vals.sk }),
          }, ['su', 'sk'])}>Conectar Supabase</Button>
        </div>
      </Card>

      <Card className="p-6">
        <div className="font-semibold">Anthropic (modo --live, opcional)</div>
        <div className="text-xs text-zinc-400 mt-0.5 mb-3">Estado: <Status ok={cfg?.anthropic} /></div>
        <div className="flex gap-2">
          <Input type="password" placeholder="sk-ant-..." value={vals.an || ''} onChange={(e) => set('an', e.target.value)} />
          <Button onClick={() => vals.an && save({ anthropic_api_key: vals.an }, ['an'])}>Guardar</Button>
        </div>
      </Card>
    </div>
  )
}
