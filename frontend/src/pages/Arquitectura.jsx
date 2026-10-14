import { motion } from 'framer-motion'
import { BrainCircuit } from 'lucide-react'
import ArchitectureBrain from '../components/ArchitectureBrain'
import { WorkspaceHero } from '../components/WorkspaceHero'
import { rise } from '../lib/motion'

export default function Arquitectura() {
  return (
    <motion.div className="workspace-page" initial="hidden" animate="show" variants={rise}>
      <WorkspaceHero eyebrow="Sistema" title="Arquitectura de ZEROAI"
        description="Explora cómo colaboran los agentes, qué motores han reportado y los resultados recientes de la operación."
        icon={BrainCircuit} />
      <section className="workspace-section">
        <ArchitectureBrain />
      </section>
    </motion.div>
  )
}
