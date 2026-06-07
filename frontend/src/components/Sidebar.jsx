import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, Users, GitBranch, Bot, TrendingUp, Briefcase, Settings,
} from 'lucide-react'
import { cn } from '../lib/util'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/leads', label: 'Leads', icon: Users },
  { to: '/pipeline', label: 'Pipeline', icon: GitBranch },
  { to: '/agentes', label: 'Agentes', icon: Bot },
  { to: '/forecast', label: 'Forecast', icon: TrendingUp },
  { to: '/clientes', label: 'Clientes', icon: Briefcase },
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

export default function Sidebar() {
  return (
    <aside className="w-60 shrink-0 fixed h-screen bg-white border-r border-zinc-200 flex flex-col">
      <div className="h-[68px] flex items-center gap-3 px-5 border-b border-zinc-100">
        <Mark />
        <div className="leading-tight">
          <div className="font-extrabold text-[17px]">
            <span style={{ color: '#173d33' }}>Zero</span><span style={{ color: '#2f8f78' }}>AI</span>
          </div>
          <div className="text-xs text-zinc-400">Lead-gen B2B</div>
        </div>
      </div>
      <nav className="p-3 flex-1 space-y-0.5">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 px-3 py-2 rounded-xl text-sm transition-colors',
                isActive ? 'bg-zinc-100 text-zinc-900 font-semibold' : 'text-zinc-500 hover:bg-zinc-50 hover:text-zinc-800',
              )
            }
          >
            <Icon size={18} />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="p-3 border-t border-zinc-100 text-xs text-zinc-400">v0.1 · local · mock</div>
    </aside>
  )
}
