import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowRight } from 'lucide-react'
import { api } from '../lib/api'
import { Card } from '../components/ui'
import { useApp } from '../App'

export default function Clientes() {
  const { clients, setClient } = useApp()
  const nav = useNavigate()
  // clients ya viene del contexto, pero re-consultamos por si cambió
  const { data = clients } = useQuery({ queryKey: ['clients'], queryFn: api.clients })

  if (!data.length) return <div className="text-zinc-400 py-16">Sin clientes aún. Usá “Buscar leads”.</div>

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {data.map((c, i) => (
        <motion.div key={c} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
          <Card onClick={() => { setClient(c); nav('/') }}
            className="p-5 cursor-pointer hover:shadow-md hover:-translate-y-0.5 transition-all">
            <div className="font-semibold">{c}</div>
            <div className="text-sm text-emerald-700 mt-1 flex items-center gap-1">Ver dashboard <ArrowRight size={14} /></div>
          </Card>
        </motion.div>
      ))}
    </div>
  )
}
