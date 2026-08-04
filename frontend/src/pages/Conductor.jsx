import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { SquareTerminal, AlertTriangle } from 'lucide-react'
import { api } from '../lib/api'
import { Card, Skeleton, pageState, SectionTitle } from '../components/ui'
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

  const roles = rolesQ.data || []
  const sessions = sessionsQ.data || []
  const latestByRole = {}
  for (const s of sessions) {
    const prev = latestByRole[s.role_id]
    if (!prev || new Date(s.started_at) > new Date(prev.started_at)) latestByRole[s.role_id] = s
  }

  const start = async (roleId) => {
    setStartingRole(roleId)
    try {
      const session = await api.conductorStartSession(roleId)
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
      <p className="text-sm text-zinc-500 max-w-2xl">
        Lanza y monitorea las terminales de Claude Code del proyecto — mismo rol, modelo y prompt
        de siempre (AGENTS, WORKER, DEBUG, DESIGN, PROMPTS, CONSULTAS), ahora desde acá en vez de
        una pestaña aparte. Las sesiones no se guardan: mueren si se reinicia el backend, igual
        que las terminales de hoy.
      </p>

      <div className="space-y-2">
        {roles.map((role) => (
          <RoleCard
            key={role.id}
            role={role}
            session={latestByRole[role.id]}
            busy={startingRole === role.id}
            onStart={() => start(role.id)}
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
