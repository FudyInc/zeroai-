import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { AlertTriangle, CircleSlash } from 'lucide-react'
import { api } from '../lib/api'
import { Card, Badge, Eyebrow, Skeleton } from './ui'
import { fade, surface, staggerDense } from '../lib/motion'

/* Qué hizo el ciclo autónomo: la última tanda, la salud por día y la cola.

   Existe por un fallo medido. Entre el 2026-08-29 y el 09-05 el ciclo estuvo ocho días
   sin ejecutar una sola tarea, con la suite en verde y `hallazgos: 0` todos los días. La
   única forma de enterarse era `journalctl`, que —como admite sincronizar-workspaces.sh—
   no lo lee nadie.

   Por eso esto muestra DATO CRUDO y no un semáforo. Un panel que dijera "todo bien" en
   verde habría dicho exactamente eso los ocho días: la auditoría mecánica pasaba, lo que
   fallaba era que nadie ejecutaba nada. Acá se ven los números y las conclusiones las
   saca quien mira. */

const ESTADOS = {
  aprobada: '#166534', pendiente: '#a16207', en_curso: '#1d4ed8',
  en_revision: '#7c3aed', rechazada: '#b45309', atascada: '#b91c1c',
  cancelada: '#71717a',
}

const fecha = (ts) =>
  ts ? new Date(ts * 1000).toLocaleString('es-CL',
    { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'

/* Un aviso de que no se pudo leer, con el motivo. NO se degrada a "sin datos": una lista
   vacía silenciosa es indistinguible de una semana sana, que es justo la confusión que
   costó los ocho días. */
function NoSePudo({ children }) {
  return (
    <Card className="p-4 flex items-start gap-2.5">
      <AlertTriangle size={16} className="text-amber-700 shrink-0 mt-0.5" />
      <p className="text-sm text-zinc-600">{children}</p>
    </Card>
  )
}

function Vacio({ children }) {
  return (
    <Card className="p-4 flex items-center gap-2.5">
      <CircleSlash size={16} className="text-pewter shrink-0" />
      <p className="text-sm text-pewter">{children}</p>
    </Card>
  )
}

/* Una barra por día. El ancho es el número de hallazgos y el color distingue si alguno
   era grave: `3 hallazgos, 0 altos` y `3 hallazgos, 3 altos` son días muy distintos. */
function BarraDeSalud({ informe }) {
  const alto = informe.altos > 0
  return (
    <div className="flex items-center gap-2.5 text-xs" title={`${informe.hallazgos} hallazgos, ${informe.altos} altos`}>
      <span className="tabular-nums text-pewter w-20 shrink-0">{informe.fecha}</span>
      <div className="flex-1 h-1.5 rounded-full bg-zinc-100 overflow-hidden">
        <div
          className={alto ? 'h-full bg-red-700' : informe.hallazgos ? 'h-full bg-amber-500' : 'h-full bg-emerald-600'}
          style={{ width: informe.hallazgos ? `${Math.min(100, informe.hallazgos * 20)}%` : '3px' }}
        />
      </div>
      <span className="tabular-nums text-zinc-500 w-24 shrink-0 text-right">
        {informe.hallazgos === 0 ? 'sin hallazgos' : `${informe.hallazgos} · ${informe.altos} altos`}
      </span>
    </div>
  )
}

/* La traza de una tarea: cada intento con su motivo. Es lo que permite ver que algo se
   intentó dos veces y por qué lo bajó el juez, sin abrir tareas.json a mano. */
function Tarea({ tarea }) {
  const historial = tarea.historial || []
  const ultimo = historial[historial.length - 1]
  return (
    <Card className="p-3.5">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm text-zinc-800 leading-snug">{tarea.titulo}</p>
        <Badge color={ESTADOS[tarea.estado] || '#71717a'}>{tarea.estado}</Badge>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-pewter">
        <span>{tarea.workspace}</span>
        {tarea.intentos > 1 && <span>{tarea.intentos} intentos</span>}
        {tarea.commit && <span className="font-mono">{String(tarea.commit).slice(0, 7)}</span>}
        {ultimo?.detalle && <span className="text-zinc-500">{ultimo.detalle}</span>}
      </div>
      {tarea.veredicto?.motivo_rechazo && (
        <p className="mt-2 text-xs text-amber-800 bg-amber-50 rounded px-2 py-1.5">
          {tarea.veredicto.motivo_rechazo}
        </p>
      )}
    </Card>
  )
}

export default function CicloPanel() {
  // La cola se mueve durante una tanda; se refresca sola. El historial de salud cambia
  // una vez al día y cada lectura cuesta un `git show` por informe: no se refresca.
  const estadoQ = useQuery({
    queryKey: ['ciclo', 'estado'], queryFn: api.cicloEstado, refetchInterval: 15000,
  })
  const saludQ = useQuery({ queryKey: ['ciclo', 'salud'], queryFn: () => api.cicloSalud(14) })

  const cola = estadoQ.data?.cola
  const tareas = estadoQ.data?.tareas || []
  const hoy = estadoQ.data?.auditoria_hoy
  const eventos = estadoQ.data?.telemetria?.eventos || []

  // Lo que se hizo, no lo que quedó pendiente: las tareas que la última tanda cerró.
  const cerradas = tareas.filter((t) => ['aprobada', 'rechazada', 'atascada'].includes(t.estado)).slice(0, 6)
  const abiertas = tareas.filter((t) => ['pendiente', 'en_curso', 'en_revision'].includes(t.estado))

  return (
    <motion.div className="space-y-5" variants={staggerDense()} initial="hidden" animate="show">
      <motion.div variants={fade}>
        <Eyebrow>El ciclo autónomo</Eyebrow>
        <p className="mt-1.5 text-sm text-pewter max-w-2xl">
          Lo que la máquina hizo sola: qué cerró la última tanda, cómo viene la salud del repo
          día a día, y qué queda en la cola. Números crudos — las conclusiones las sacas tú.
        </p>
      </motion.div>

      {/* --- 1. La última tanda ------------------------------------------------ */}
      <motion.section className="space-y-2" variants={fade}>
        <div className="flex items-baseline justify-between">
          <Eyebrow>Últimas tareas cerradas</Eyebrow>
          {cola && (
            <span className="text-xs text-pewter tabular-nums">
              {cola.abiertas} abiertas · {cola.total} en total
            </span>
          )}
        </div>
        {estadoQ.isLoading ? <Skeleton className="h-20 w-full" />
          : estadoQ.error ? <NoSePudo>No se pudo leer el estado del ciclo: {String(estadoQ.error.message)}</NoSePudo>
            : cerradas.length === 0 ? <Vacio>El ciclo todavía no cerró ninguna tarea.</Vacio>
              : (
                <motion.div className="space-y-2" variants={staggerDense()} initial="hidden" animate="show">
                  {cerradas.map((t) => (
                    <motion.div key={t.id} variants={surface}><Tarea tarea={t} /></motion.div>
                  ))}
                </motion.div>
              )}
      </motion.section>

      {/* --- 2. Salud por día --------------------------------------------------- */}
      <motion.section className="space-y-2" variants={fade}>
        <Eyebrow>Salud del repo, día a día</Eyebrow>
        {saludQ.isLoading ? <Skeleton className="h-24 w-full" />
          : saludQ.error ? <NoSePudo>No se pudo leer el historial: {String(saludQ.error.message)}</NoSePudo>
            /* `disponible: false` viene con motivo del backend. Mostrarlo como "sin
               hallazgos" sería la mentira exacta de agosto. */
            : !saludQ.data?.disponible ? <NoSePudo>{saludQ.data?.motivo || 'Historial no disponible.'}</NoSePudo>
              : (
                <Card className="p-4 space-y-2">
                  {saludQ.data.informes.map((i) => <BarraDeSalud key={i.fecha} informe={i} />)}
                </Card>
              )}
        {hoy && (
          <p className="text-xs text-pewter">
            Hoy: {hoy.hallazgos} hallazgos ({hoy.altos} altos) sobre {hoy.checks?.length || 0} comprobaciones
            {hoy.cuando ? ` · ${fecha(hoy.cuando)}` : ''}
          </p>
        )}
      </motion.section>

      {/* --- 3. La cola y los agentes ------------------------------------------ */}
      <motion.section className="space-y-2" variants={fade}>
        <Eyebrow>En la cola</Eyebrow>
        {abiertas.length === 0
          ? <Vacio>Nada pendiente. El planificador encola solo lo que haya que hacer.</Vacio>
          : (
            <motion.div className="space-y-2" variants={staggerDense()} initial="hidden" animate="show">
              {abiertas.map((t) => (
                <motion.div key={t.id} variants={surface}><Tarea tarea={t} /></motion.div>
              ))}
            </motion.div>
          )}
        {/* `ms`, no `seconds`: es la clave que emite zero/telemetry.py. */}
        {eventos.length > 0 && (
          <p className="text-xs text-pewter">
            Último agente: {eventos[0].agent || '—'}
            {eventos[0].engine ? ` · ${eventos[0].engine}` : ''}
            {eventos[0].ms != null ? ` · ${(Number(eventos[0].ms) / 1000).toFixed(1)}s` : ''}
            {eventos[0].status ? ` · ${eventos[0].status}` : ''}
          </p>
        )}
      </motion.section>
    </motion.div>
  )
}
