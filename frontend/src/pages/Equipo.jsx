import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { ShieldCheck, AlertTriangle, Circle } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { Card, Skeleton, Select, pageState } from '../components/ui'
import { ROLE_LABELS } from '../lib/roles'
import { rise, fade, surface, stagger } from '../lib/motion'
import { WorkspaceHero, WorkspaceSectionHeading } from '../components/WorkspaceHero'

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

  const setClients = useMutation({
    mutationFn: ({ id, clients }) => api.setTeamClients(id, clients),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['team'] })
      toast.success('Clientes actualizados')
    },
    onError: (e) => {
      qc.invalidateQueries({ queryKey: ['team'] })   // deshace la actualización optimista
      toast.error('No se pudieron guardar los clientes: ' + e.message)
    },
  })

  // La lista se arma desde el caché más reciente (no desde el render que pintó
  // el checkbox) y se escribe de inmediato: dos clics seguidos suman, no se pisan.
  const toggleClient = (id, client) => {
    const actual = qc.getQueryData(['team'])?.users?.find((x) => x.id === id)?.clients || []
    const clients = actual.includes(client) ? actual.filter((x) => x !== client) : [...actual, client]
    qc.setQueryData(['team'], (old) => old && ({
      ...old, users: old.users.map((x) => (x.id === id ? { ...x, clients } : x)),
    }))
    setClients.mutate({ id, clients })
  }
  const { data: allClients = [] } = useQuery({ queryKey: ['clients'], queryFn: api.clients })

  const gate = pageState({
    isLoading, error, onRetry: refetch,
    isEmpty: !data?.users?.length, emptyText: 'Sin cuentas todavía.',
    skeleton: <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-16 w-full" />)}</div>,
  })
  if (gate) return gate

  const { users, configured } = data

  return (
    <motion.div className="workspace-page" initial="hidden" animate="show" variants={rise}>
      <motion.div variants={surface}>
        <WorkspaceHero eyebrow="Administración" title="Equipo"
          description="Revisa las cuentas del dashboard, sus roles, actividad reciente y trabajo pendiente."
          icon={ShieldCheck}
          aside={{ label: 'Miembros registrados', value: users.length, detail: 'Administra el acceso desde cada perfil' }} />
      </motion.div>

      <section className="workspace-section">
        <WorkspaceSectionHeading eyebrow="Accesos" title="Miembros del equipo"
          description="Las horas activas (meta CCO: 20 h por semana) son una aproximación de uso del dashboard; no incluyen llamadas, WhatsApp desde el celular ni reuniones." />

      {!configured && (
        <motion.div variants={fade}>
          <Card className="p-4 flex items-start gap-3 bg-amber-50/60 border-amber-200">
          <AlertTriangle size={17} className="text-amber-700 shrink-0 mt-0.5" />
          <div className="text-sm text-amber-800">
            Falta conectar Supabase (URL + key) para ver las cuentas reales — sin eso este panel
              no tiene de dónde leer.
            </div>
          </Card>
        </motion.div>
      )}

      <motion.div className="grid gap-4 max-w-4xl" variants={stagger()} initial="hidden" animate="show">
        {users.map((u) => (
          <motion.div key={u.id} variants={surface}>
            <Card className={'p-5 ' + (!u.role ? 'bg-amber-50/40 border-amber-200' : '')}>
              <div className="flex flex-wrap sm:flex-nowrap items-center gap-4">
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
                {u.role && (u.pending_work != null || u.week_goal_hours != null) && (
                  <div className="flex items-center gap-4 mt-1.5">
                    {u.pending_work != null && (
                      <span className="text-xs text-zinc-500">
                        <b className="text-zinc-700 tabular-nums">{u.pending_work}</b> pendiente{u.pending_work === 1 ? '' : 's'}
                      </span>
                    )}
                    {u.week_goal_hours != null && (
                      <div className="flex items-center gap-2 flex-1 max-w-[220px]">
                        <div className="flex-1 h-1.5 rounded-full bg-zinc-100 overflow-hidden">
                          <div
                            className="h-full rounded-full bg-gold-deep transition-all"
                            style={{ width: `${Math.min(100, (u.week_hours / u.week_goal_hours) * 100)}%` }}
                          />
                        </div>
                        <span className="text-[11px] text-zinc-400 tabular-nums shrink-0">
                          {u.week_hours.toFixed(1)}/{u.week_goal_hours}h esta semana
                        </span>
                      </div>
                    )}
                  </div>
                )}
              </div>
              <Select
                value={u.role || ''}
                onChange={(e) => setRole.mutate({ id: u.id, role: e.target.value || null })}
                disabled={setRole.isPending}
                className="w-full sm:w-32 shrink-0"
              >
                <option value="">Sin acceso</option>
                <option value="admin">{ROLE_LABELS.admin}</option>
                <option value="cro">{ROLE_LABELS.cro}</option>
                <option value="cto">{ROLE_LABELS.cto}</option>
                <option value="cco">{ROLE_LABELS.cco}</option>
                <option value="operador">{ROLE_LABELS.operador}</option>
              </Select>
              </div>
              {u.role === 'operador' && (
                <fieldset className="mt-3 pt-3 border-t border-zinc-100" disabled={setClients.isPending}>
                  <legend className="text-xs font-medium text-zinc-500 mb-1.5">
                    Clientes asignados: {(u.clients || []).length ? u.clients.join(', ') : 'ninguno (no verá ningún cliente)'}
                  </legend>
                  <div className="flex flex-wrap gap-x-4 gap-y-1.5">
                    {allClients.map((c) => {
                      const assigned = (u.clients || []).includes(c)
                      return (
                        <label key={c} className="flex items-center gap-1.5 text-sm text-zinc-700 cursor-pointer">
                          <input type="checkbox" className="accent-gold" checked={assigned}
                            onChange={() => toggleClient(u.id, c)} />
                          {c}
                        </label>
                      )
                    })}
                  </div>
                  <p className="text-[11px] text-zinc-400 mt-2">Los cambios de clientes aplican al próximo inicio de sesión (hasta 1 hora).</p>
                </fieldset>
              )}
            </Card>
          </motion.div>
        ))}
      </motion.div>
      </section>
    </motion.div>
  )
}
