import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  LayoutDashboard, Users, GitBranch, Bot, TrendingUp, Briefcase, Settings, Mail, Network, LogOut, Megaphone,
} from 'lucide-react'
import { cn } from '../lib/util'
import { api } from '../lib/api'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/vender', label: 'Vender', icon: Mail },
  { to: '/campanas', label: 'Campañas', icon: Megaphone },
  { to: '/leads', label: 'Leads', icon: Users },
  { to: '/pipeline', label: 'Pipeline', icon: GitBranch },
  { to: '/agentes', label: 'Agentes', icon: Bot },
  { to: '/forecast', label: 'Forecast', icon: TrendingUp },
  { to: '/clientes', label: 'Clientes', icon: Briefcase },
  { to: '/arquitectura', label: 'Arquitectura', icon: Network },
  { to: '/config', label: 'Configuración', icon: Settings },
]

function Mark() {
  return (
    <svg width="34" height="34" viewBox="0 0 48 48" className="shrink-0">
      <rect width="48" height="48" rx="12" fill="#173d33" />
      <ellipse cx="24" cy="24" rx="8.5" ry="12.5" fill="none" stroke="#f4efe3" strokeWidth="4" />
      <line x1="16.5" y1="33" x2="31.5" y2="15" stroke="#f4efe3" strokeWidth="4" strokeLinecap="round" />
    </svg>
  )
}

// Colapsado muestra solo íconos; al pasar el mouse se expande y aparecen las etiquetas.
export default function Sidebar() {
  const [open, setOpen] = useState(false)
  const label = (text) => (
    <motion.span
      animate={{ opacity: open ? 1 : 0, width: open ? 'auto' : 0 }}
      transition={{ duration: 0.2 }}
      className="whitespace-nowrap overflow-hidden"
    >
      {text}
    </motion.span>
  )
  return (
    <motion.aside
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      animate={{ width: open ? 240 : 76 }}
      transition={{ type: 'spring', stiffness: 300, damping: 30 }}
      className="sticky top-0 h-screen shrink-0 z-40 bg-white border-r border-zinc-200 flex flex-col overflow-hidden"
    >
      <div className="h-[68px] flex items-center gap-3 px-[20px] border-b border-zinc-100 shrink-0">
        <Mark />
        <motion.div
          animate={{ opacity: open ? 1 : 0 }}
          transition={{ duration: 0.2 }}
          className="leading-tight whitespace-nowrap"
        >
          <div className="font-extrabold text-[17px]">
            <span style={{ color: '#173d33' }}>Zero</span><span style={{ color: '#2f8f78' }}>AI</span>
          </div>
          <div className="text-xs text-zinc-400">Lead-gen B2B</div>
        </motion.div>
      </div>

      <nav className="p-3 flex-1 space-y-0.5">
        {NAV.map(({ to, label: text, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            title={text}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 px-3 py-2 rounded-xl text-sm transition-colors',
                isActive ? 'bg-zinc-100 text-zinc-900 font-semibold' : 'text-zinc-500 hover:bg-zinc-50 hover:text-zinc-800',
              )
            }
          >
            <Icon size={18} className="shrink-0" />
            {label(text)}
          </NavLink>
        ))}
      </nav>

      <div className="p-3 border-t border-zinc-100 space-y-1">
        <button
          onClick={() => api.logout()}
          title="Cerrar sesión"
          className="flex items-center gap-3 px-3 py-2 rounded-xl text-sm text-zinc-500 hover:bg-zinc-50 hover:text-zinc-800 transition-colors w-full"
        >
          <LogOut size={18} className="shrink-0" />
          {label('Cerrar sesión')}
        </button>
        <motion.div animate={{ opacity: open ? 1 : 0 }} transition={{ duration: 0.2 }}
          className="text-[11px] text-zinc-400 px-3 whitespace-nowrap overflow-hidden">
          v0.1 · local
        </motion.div>
      </div>
    </motion.aside>
  )
}
