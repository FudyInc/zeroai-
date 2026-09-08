import { motion } from 'framer-motion'
import ArchitectureBrain from '../components/ArchitectureBrain'
import { rise } from '../lib/motion'

export default function Arquitectura() {
  return (
    <motion.div initial="hidden" animate="show" variants={rise}>
      <ArchitectureBrain />
    </motion.div>
  )
}
