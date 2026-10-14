import { motion } from 'framer-motion'
import { Activity } from 'lucide-react'
import { WorkspaceHero, WorkspaceSectionHeading } from '../components/WorkspaceHero'
import CicloPanel from '../components/CicloPanel'
import { rise, fade } from '../lib/motion'

/* Qué hizo el sistema por su cuenta: la cola de trabajo autónomo, la telemetría
   de los agentes y el historial de la auditoría diaria.

   Antes esta página se llamaba Conductor y tenía dos mitades pegadas. La otra
   lanzaba sesiones del CLI `claude` desde el dashboard — 884 líneas de Python,
   11 endpoints y un WebSocket para replicar lo que ya hacen las pestañas de
   terminal de siempre. Nunca se usó (el registro de sesiones vivía en memoria y
   estaba vacío), así que se sacó entera el 2026-09-09.

   Esta mitad se quedó porque se ganó el puesto: el mismo día que se revisó, su
   informe de salud avisó de 5 tests rotos que la suite local daba por verdes —
   el fallo solo aparecía en el checkout con el .env real. */
export default function Ciclo() {
  return (
    <motion.div className="workspace-page" initial="hidden" animate="show" variants={rise}>
      <motion.div variants={fade}>
        <WorkspaceHero eyebrow="Operación autónoma" title="Ciclo autónomo"
          description="Lo que ZERO hizo sin que nadie lo pidiera: qué tareas tomó, qué agentes corrieron y con qué motor, y qué encontró la auditoría diaria."
          icon={Activity} />
      </motion.div>
      <section className="workspace-section max-w-3xl">
        <WorkspaceSectionHeading eyebrow="Actividad" title="Trabajo y auditoría"
          description="Consulta las tareas, la telemetría y los informes de salud del sistema." />
        <motion.div variants={fade}>
          <CicloPanel />
        </motion.div>
      </section>
    </motion.div>
  )
}
