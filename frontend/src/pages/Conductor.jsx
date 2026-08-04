import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { SquareTerminal, AlertTriangle } from 'lucide-react'
import { api } from '../lib/api'
import { Card, Skeleton, pageState, SectionTitle, Eyebrow } from '../components/ui'
import RoleCard from '../components/conductor/RoleCard'
import SessionChat from '../components/conductor/SessionChat'

/* Panel exclusivo del admin: lanza y monitorea las terminales de Claude Code
   del proyecto (mismos 6 roles que hoy usan los *-terminal.sh — ver
   zero/conductor.py) desde el dashboard en vez de una pestaña de Ptyxis
   aparte. Local-only: /api/conductor/status gatea la página entera si el
   CLI `claude` no está disponible en este servidor (ej. Render). */
export default function Conductor() {
  const qc = useQueryClient()
  const [openSessionId, setOpenSessionId] = useState(null)
  const [startingRole, setStartingRole] = useState(null)
  // Modelo elegido por rol, solo mientras dura la vista. El default viene del
  // backend (role.default_model); esto guarda únicamente lo que el usuario
  // cambia a mano antes de darle Iniciar.
  const [modelByRole, setModelByRole] = useState({})

  const statusQ = useQuery({ queryKey: ['conductor', 'status'], queryFn: api.conductorStatus })
  const rolesQ = useQuery({
    queryKey: ['conductor', 'roles'], queryFn: api.conductorRoles,
    enabled: !!statusQ.data?.available,
  })
  const sessionsQ = useQuery({
    queryKey: ['conductor', 'sessions'], queryFn: api.conductorSessions,
    enabled: !!statusQ.data?.available,
    refetchInterval: 5000,
  })

  const gate = pageState({
    isLoading: statusQ.isLoading, error: statusQ.error, onRetry: statusQ.refetch,
    skeleton: <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-16 w-full" />)}</div>,
  })
  if (gate) return gate

  if (!statusQ.data?.available) {
    return (
      <div className="max-w-xl">
        <div className="flex items-center gap-2 mb-4">
          <SquareTerminal size={18} className="text-gold-deep" />
          <SectionTitle>Conductor</SectionTitle>
        </div>
        <Card className="p-6 flex items-start gap-3">
          <AlertTriangle size={17} className="text-amber-700 shrink-0 mt-0.5" />
          <div className="text-sm text-zinc-600">
            <p className="font-medium text-zinc-800">Esta función solo corre local.</p>
            <p className="mt-1">
              {statusQ.data?.reason || 'El CLI de Claude Code no está disponible en este servidor.'}
            </p>
          </div>
        </Card>
      </div>
    )
  }

  const roles = rolesQ.data?.roles || []
  const models = rolesQ.data?.models || []
  const sessions = sessionsQ.data || []
  const latestByRole = {}
  for (const s of sessions) {
    const prev = latestByRole[s.role_id]
    if (!prev || new Date(s.started_at) > new Date(prev.started_at)) latestByRole[s.role_id] = s
  }

  const modelFor = (role) =>
    modelByRole[role.id] || role.default_model || models[0]?.id || 'sonnet'

  const start = async (role) => {
    setStartingRole(role.id)
    try {
      const session = await api.conductorStartSession(role.id, modelFor(role))
      qc.invalidateQueries({ queryKey: ['conductor', 'sessions'] })
      setOpenSessionId(session.id)
    } catch (e) {
      if (e.status === 409 && e.body?.existing_session_id) {
        // Ya hay una corriendo para ese rol — nos adjuntamos en vez de fallar.
        setOpenSessionId(e.body.existing_session_id)
      } else {
        toast.error('No se pudo iniciar: ' + e.message)
      }
    } finally {
      setStartingRole(null)
    }
  }

  const stop = async (sessionId) => {
    try {
      await api.conductorStop(sessionId)
      qc.invalidateQueries({ queryKey: ['conductor', 'sessions'] })
    } catch (e) {
      toast.error('No se pudo detener: ' + e.message)
    }
  }

  return (
    <div className="space-y-5 max-w-3xl">
      <div className="flex items-center gap-2">
        <SquareTerminal size={18} className="text-gold-deep" />
        <SectionTitle>Conductor</SectionTitle>
      </div>
      <p className="text-sm text-pewter max-w-2xl">
        Lanza y monitorea las terminales de Claude Code del proyecto. El rol define qué zona del
        repo toca cada terminal; el modelo, cuánto piensa — se elige antes de iniciar. Las sesiones
        no se guardan: mueren si se reinicia el backend, igual que las terminales de hoy.
      </p>

      <div className="space-y-2">
        <Eyebrow>Terminales</Eyebrow>
        {roles.map((role) => (
          <RoleCard
            key={role.id}
            role={role}
            models={models}
            model={modelFor(role)}
            onModelChange={(m) => setModelByRole((prev) => ({ ...prev, [role.id]: m }))}
            session={latestByRole[role.id]}
            busy={startingRole === role.id}
            onStart={() => start(role)}
            onOpen={() => setOpenSessionId(latestByRole[role.id]?.id)}
            onStop={() => stop(latestByRole[role.id]?.id)}
          />
        ))}
      </div>

      {openSessionId && (
        <SessionChat sessionId={openSessionId} onClose={() => setOpenSessionId(null)} />
      )}
    </div>
  )
}
