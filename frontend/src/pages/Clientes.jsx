import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowRight } from 'lucide-react'
import { api } from '../lib/api'
import { Card, Skeleton, Button } from '../components/ui'
import { useApp } from '../App'

export default function Clientes() {
  const { setClient } = useApp()
  const nav = useNavigate()
  const { data = [], isLoading, error, refetch } = useQuery({ queryKey: ['clients'], queryFn: api.clients })

  if (isLoading) return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {[0, 1, 2].map((i) => <Skeleton key={i} className="h-24 w-full" />)}
    </div>
  )
  if (error) return (
    <div className="py-16 text-center">
      <p className="text-rose-600 font-medium">No se pudieron cargar los clientes.</p>
      <Button variant="soft" className="mt-3" onClick={() => refetch()}>Reintentar</Button>
    </div>
  )
  if (!data.length) return <div className="text-zinc-400 py-16 text-center">Sin clientes aún. Usá “Buscar leads”.</div>

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {data.map((c, i) => (
        <motion.div key={c} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
          <Card onClick={() => { setClient(c); nav('/') }}
            className="p-5 cursor-pointer hover:shadow-md hover:-translate-y-0.5 transition-all">
            <div className="font-semibold capitalize">{c}</div>
            <div className="text-sm text-emerald-700 mt-1 flex items-center gap-1">Ver dashboard <ArrowRight size={14} /></div>
          </Card>
        </motion.div>
      ))}
    </div>
  )
}
