import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { ShieldCheck, AlertTriangle, Circle } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { Card, Skeleton, Select, pageState, SectionTitle } from '../components/ui'
import { ROLE_LABELS } from '../lib/roles'

/* Panel exclusivo del admin (Diego): quién tiene cuenta en el dashboard, qué
   rol tiene cada uno (o ninguno todavía — alguien que entró con Google pero
   nadie le dio acceso), y una aproximación de quién está conectado ahora
   mismo. El backend ya lo protege (admin-only, sin entrada en
   _ROLE_ALLOWED); acá solo se construye la vista. */

const timeAgo = (iso) => {
  if (!iso) return 'nunca'
  const ms = Date.now() - new Date(iso).getTime()
  const min = Math.round(ms / 60000)
  if (min < 1) return 'recién'
  if (min < 60) return `hace ${min} min`
  const h = Math.round(min / 60)
  if (h < 24) return `hace ${h} h`
  return `hace ${Math.round(h / 24)} d`
}

export default function Equipo() {
  const qc = useQueryClient()
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ['team'], queryFn: api.team })

  const setRole = useMutation({
    mutationFn: ({ id, role }) => api.setTeamRole(id, role || null),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['team'] })
      toast.success('Rol actualizado')
    },
    onError: (e) => toast.error('No se pudo cambiar el rol: ' + e.message),
  })

  const gate = pageState({
    isLoading, error, onRetry: refetch,
    isEmpty: !data?.users?.length, emptyText: 'Sin cuentas todavía.',
    skeleton: <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-16 w-full" />)}</div>,
  })
  if (gate) return gate

  const { users, configured } = data

  return (
    <div className="space-y-5 max-w-3xl">
      <div className="flex items-center gap-2">
        <ShieldCheck size={18} className="text-gold-deep" />
        <SectionTitle>Equipo</SectionTitle>
      </div>
      <p className="text-sm text-zinc-500 max-w-2xl">
        Quién tiene cuenta, qué rol tiene y quién está conectado ahora. "En línea" es una
        aproximación (actividad en los últimos 5 minutos contra este servidor) — no un sistema
        de presencia en tiempo real.
      </p>

      {!configured && (
        <Card className="p-4 flex items-start gap-3 bg-amber-50/60 border-amber-200">
          <AlertTriangle size={17} className="text-amber-700 shrink-0 mt-0.5" />
          <div className="text-sm text-amber-800">
            Falta conectar Supabase (URL + key) para ver las cuentas reales — sin eso este panel
            no tiene de dónde leer.
          </div>
        </Card>
      )}

      <div className="space-y-2">
        {users.map((u, i) => (
          <motion.div key={u.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.03 }}>
            <Card className={'p-4 flex items-center gap-4 ' + (!u.role ? 'bg-amber-50/40 border-amber-200' : '')}>
              <div className="w-10 h-10 rounded-full bg-champagne/40 text-gold-deep grid place-items-center shrink-0 font-bold text-sm">
                {(u.full_name || u.email || '?').trim().charAt(0).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-zinc-800 truncate">{u.full_name || u.email || '—'}</span>
                  {u.online ? (
                    <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-600">
                      <Circle size={7} className="fill-emerald-500 text-emerald-500" /> en línea
                    </span>
                  ) : (
                    <span className="text-[11px] text-zinc-400">visto {timeAgo(u.last_seen_here ? new Date(u.last_seen_here * 1000).toISOString() : null)}</span>
                  )}
                </div>
                <div className="text-xs text-zinc-400 truncate mt-0.5">
                  {u.email} · cuenta creada {timeAgo(u.created_at)} · último login {timeAgo(u.last_sign_in_at)}
                </div>
                {!u.role && (
                  <div className="text-xs text-amber-700 font-medium mt-1">Sin rol asignado — no puede usar el dashboard todavía.</div>
                )}
              </div>
              <Select
                value={u.role || ''}
                onChange={(e) => setRole.mutate({ id: u.id, role: e.target.value || null })}
                disabled={setRole.isPending}
                className="w-32 shrink-0"
              >
                <option value="">Sin acceso</option>
                <option value="admin">{ROLE_LABELS.admin}</option>
                <option value="cro">{ROLE_LABELS.cro}</option>
                <option value="cto">{ROLE_LABELS.cto}</option>
                <option value="cco">{ROLE_LABELS.cco}</option>
              </Select>
            </Card>
          </motion.div>
        ))}
      </div>
    </div>
  )
}
