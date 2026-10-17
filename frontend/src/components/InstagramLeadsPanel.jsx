import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { RefreshCw } from 'lucide-react'
import ChannelIcon from './ChannelIcon'
import { api } from '../lib/api'
import { Card, Button, Eyebrow, SectionTitle } from './ui'

/* Importación de leads desde formularios de Instagram (Meta Lead Ads). El
   backend también importa solo cada 5 min; el botón es "importar ahora".
   Vive aparte de Agentes.jsx porque lo usan el admin (como tarjeta expandible)
   y el operador (único panel que ve). El token de Meta es solo del admin: acá
   solo se pegan los IDs de formulario. */

export const igStatusKey = (client) => ['instagram-status', client]

export function ago(iso, now = Date.now()) {
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return '—'
  const s = Math.max(0, Math.round((now - t) / 1000))
  if (s < 60) return 'hace instantes'
  const m = Math.round(s / 60)
  if (m < 60) return `hace ${m} min`
  const h = Math.round(m / 60)
  if (h < 24) return `hace ${h} h`
  const d = Math.round(h / 24)
  return `hace ${d} ${d === 1 ? 'día' : 'días'}`
}

const parseIds = (txt) => txt.split(/[\s,;]+/).map((x) => x.trim()).filter(Boolean)

export function useInstagramStatus(client) {
  return useQuery({ queryKey: igStatusKey(client), queryFn: () => api.instagramStatus(client), enabled: !!client })
}

export default function InstagramLeadsPanel({ client }) {
  const qc = useQueryClient()
  const statusQ = useInstagramStatus(client)
  const st = statusQ.data
  const [text, setText] = useState('')
  const [saving, setSaving] = useState(false)
  const [syncing, setSyncing] = useState(false)

  const savedKey = (st?.lead_form_ids || []).join(',')
  useEffect(() => { setText((st?.lead_form_ids || []).join('\n')) }, [savedKey, client]) // eslint-disable-line react-hooks/exhaustive-deps

  const ids = st?.lead_form_ids || []
  const dirty = parseIds(text).join(',') !== savedKey

  async function save() {
    setSaving(true)
    try {
      const next = await api.setInstagramForms(client, parseIds(text))
      qc.setQueryData(igStatusKey(client), next)
      toast.success('Formularios guardados.')
    } catch (e) {
      toast.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  async function importNow() {
    setSyncing(true)
    try {
      const r = await api.syncAdLeads(client)
      toast.success(`${r.created} nuevos · ${r.already_present} ya estaban · ${r.skipped_blocked} bloqueados`)
      qc.invalidateQueries({ queryKey: ['board'] })
      qc.invalidateQueries({ queryKey: ['leads'] })
      qc.invalidateQueries({ queryKey: ['kpis'] })
      qc.invalidateQueries({ queryKey: igStatusKey(client) })
    } catch (e) {
      toast.error(e.message)
      qc.invalidateQueries({ queryKey: igStatusKey(client) })
    } finally {
      setSyncing(false)
    }
  }

  const blocker = !st ? null
    : !st.connected ? 'Meta no conectado: pídele al administrador que conecte la cuenta.'
    : ids.length === 0 ? 'Asigna al menos un ID de formulario para poder importar.'
    : dirty ? 'Guarda los cambios en los formularios antes de importar.'
    : null

  const ls = st?.last_sync

  return (
    <Card className="p-5 space-y-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="w-11 h-11 rounded-xl grid place-items-center bg-white border border-zinc-200"><ChannelIcon channel="ig" /></div>
          <div>
            <Eyebrow>Instagram · Lead Ads</Eyebrow>
            <SectionTitle>Leads desde formularios</SectionTitle>
          </div>
        </div>
        {st && (
          <span className={'text-xs font-medium px-2 py-1 rounded-full ' + (st.connected ? 'text-gold-deep bg-champagne/30' : 'text-amber-700 bg-amber-50')}>
            {st.connected ? 'Conectado' : 'Meta no conectado'}
          </span>
        )}
      </div>

      <p className="text-sm text-zinc-500 max-w-2xl">
        Trae los leads de los formularios de anuncios de Instagram (renta y teléfono) a tu Pipeline.
        Se importan solos cada 5 minutos; el botón de abajo es para importar ahora.
      </p>

      {statusQ.isLoading && <div className="text-sm text-zinc-400">Cargando estado…</div>}
      {statusQ.isError && (
        <div className="text-sm text-rose-600">
          No se pudo cargar el estado: {statusQ.error.message}{' '}
          <button className="underline" onClick={() => statusQ.refetch()}>Reintentar</button>
        </div>
      )}

      {st && (
        <>
          <div className="space-y-2">
            <div className="text-sm font-medium text-zinc-700">Formularios asignados</div>
            {ids.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {ids.map((id) => (
                  <span key={id} className="font-mono text-xs px-2 py-1 rounded-lg bg-zinc-100 text-zinc-700">{id}</span>
                ))}
              </div>
            ) : <div className="text-sm text-zinc-400">Ninguno todavía.</div>}
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={3}
              placeholder="Pega los IDs de formulario, separados por coma o salto de línea"
              className="w-full border border-zinc-200 dark:border-zinc-700/50 bg-white dark:bg-zinc-50 rounded-xl px-3 py-2 text-sm font-mono outline-none transition focus:ring-4 focus:ring-champagne/40 focus:border-gold/60 placeholder:text-zinc-400 dark:placeholder:text-zinc-600"
            />
            <Button variant="soft" onClick={save} disabled={saving || !dirty}>
              {saving ? 'Guardando…' : 'Guardar formularios'}
            </Button>
          </div>

          <div className="text-sm text-zinc-600 border-t border-zinc-100 pt-4">
            <span className="font-medium text-zinc-700">Última importación: </span>
            {!ls ? 'aún no hay'
              : ls.error ? <span className="text-rose-600">{ago(ls.at)} falló — {ls.error}</span>
              : `${ago(ls.at)} — ${ls.created} nuevos de ${ls.read} leídos`}
            {ls?.failed_forms?.length > 0 && (
              <span className="text-rose-600"> · formularios con error: {ls.failed_forms.map(f => f.form_id).join(', ')}</span>
            )}
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            <Button onClick={importNow} disabled={syncing || !!blocker}>
              <RefreshCw size={14} className={syncing ? 'animate-spin' : ''} />
              {syncing ? 'Importando…' : 'Importar leads de Instagram'}
            </Button>
            {blocker && <span className="text-sm text-amber-700">{blocker}</span>}
          </div>
        </>
      )}
    </Card>
  )
}
