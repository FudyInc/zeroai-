import { useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  LayoutDashboard, Users, GitBranch, Bot, TrendingUp, Briefcase, Settings, Mail, Network, LogOut, Megaphone, X, User, Wallet, AlertTriangle, ShieldCheck,
} from 'lucide-react'
import { cn } from '../lib/util'
import { api } from '../lib/api'
import { canSeePage, ROLE_LABELS } from '../lib/roles'

const SECTIONS = [
  {
    title: 'Operación', items: [
      { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
      { to: '/leads', label: 'Leads', icon: Users },
      { to: '/pipeline', label: 'Pipeline', icon: GitBranch },
      { to: '/forecast', label: 'Forecast', icon: TrendingUp },
    ],
  },
  {
    title: 'Crecimiento', items: [
      { to: '/vender', label: 'Vender', icon: Mail },
      { to: '/campanas', label: 'Campañas', icon: Megaphone },
      { to: '/agentes', label: 'Agentes', icon: Bot },
    ],
  },
  {
    title: 'Cuenta', items: [
      { to: '/clientes', label: 'Clientes', icon: Briefcase },
      { to: '/finanzas', label: 'Finanzas', icon: Wallet },
      { to: '/arquitectura', label: 'Arquitectura', icon: Network },
      { to: '/config', label: 'Configuración', icon: Settings },
      { to: '/equipo', label: 'Equipo', icon: ShieldCheck },
    ],
  },
]

function Mark() {
  return (
    <img src="/logo-mark.png" alt="ZeroAI" width="34" height="34" className="shrink-0" />
  )
}

/* Escritorio: colapsado muestra solo íconos y se expande al pasar el mouse.
   Móvil (<md): drawer fijo fuera de pantalla; se abre con el botón del header
   (mobileOpen/onClose vienen de App) y se cierra al navegar o tocar el fondo. */
export default function Sidebar({ mobileOpen = false, onClose = () => {}, username = null, fullName = null, role = null, authEnabled = false }) {
  const [hover, setHover] = useState(false)
  const open = hover || mobileOpen
  const visibleSections = SECTIONS
    .map((sec) => ({ ...sec, items: sec.items.filter((i) => canSeePage(i.to, role, authEnabled)) }))
    .filter((sec) => sec.items.length > 0)
  const noRoleAssigned = authEnabled && !role
  const reveal = (text) => (
    <motion.span animate={{ opacity: open ? 1 : 0, width: open ? 'auto' : 0 }} transition={{ duration: 0.2 }}
      className="whitespace-nowrap overflow-hidden">{text}</motion.span>
  )
  return (
    <>
      <AnimatePresence>
        {mobileOpen && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm md:hidden" onClick={onClose} />
        )}
      </AnimatePresence>

      <motion.aside
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        animate={{ width: open ? 240 : 76 }}
        transition={{ type: 'spring', stiffness: 300, damping: 30 }}
        className={cn(
          'h-screen shrink-0 z-50 bg-white border-r border-zinc-200 flex flex-col overflow-hidden',
          'max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:transition-transform max-md:duration-300',
          mobileOpen ? 'max-md:translate-x-0' : 'max-md:-translate-x-full',
          'md:sticky md:top-0 md:translate-x-0',
        )}
      >
        <div className="h-[68px] flex items-center gap-3 px-[20px] border-b border-zinc-100 shrink-0">
          <Link to="/" onClick={onClose} title="Ir al Dashboard"
            className="flex items-center gap-3 flex-1 min-w-0 rounded-lg transition-opacity hover:opacity-70">
            <Mark />
            <motion.div animate={{ opacity: open ? 1 : 0 }} transition={{ duration: 0.2 }} className="leading-tight whitespace-nowrap">
              <div className="font-display font-extrabold text-[17px] tracking-tight text-brand">
                ZEROAI
              </div>
              <div className="text-xs text-pewter">Lead-gen B2B</div>
            </motion.div>
          </Link>
          {mobileOpen && (
            <button onClick={onClose} aria-label="Cerrar menú" className="md:hidden p-1.5 rounded-lg text-zinc-500 hover:bg-zinc-100">
              <X size={18} />
            </button>
          )}
        </div>

        <nav className="p-3 flex-1 space-y-4 overflow-y-auto overflow-x-hidden">
          {noRoleAssigned && (
            <div className="flex items-center gap-3 text-amber-700 bg-amber-50 rounded-xl px-3 py-2" title="Sin rol asignado — contacta al administrador">
              <AlertTriangle size={18} className="shrink-0" />
              {reveal(<span className="text-xs">Sin rol asignado — contacta al administrador.</span>)}
            </div>
          )}
          {visibleSections.map((sec) => (
            <div key={sec.title} className="space-y-0.5">
              <div className="h-4 px-3 flex items-end">
                <motion.span animate={{ opacity: open ? 1 : 0 }} transition={{ duration: 0.2 }}
                  className="text-[10px] font-semibold uppercase tracking-wider text-pewter whitespace-nowrap overflow-hidden">
                  {sec.title}
                </motion.span>
              </div>
              {sec.items.map(({ to, label: text, icon: Icon, end }) => (
                <NavLink key={to} to={to} end={end} title={text} onClick={onClose}
                  className={({ isActive }) => cn(
                    'flex items-center gap-3 px-3 py-2 rounded-xl text-sm transition-colors',
                    isActive ? 'bg-zinc-100 text-zinc-900 font-semibold' : 'text-zinc-500 hover:bg-zinc-50 hover:text-zinc-800',
                  )}>
                  <Icon size={18} className="shrink-0" />
                  {reveal(text)}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="p-3 border-t border-zinc-100 space-y-1">
          {username && (() => {
            const roleLabel = ROLE_LABELS[role] || role
            const displayName = fullName || username
            const subLine = fullName ? [roleLabel, username].filter(Boolean).join(' · ') : roleLabel
            return (
              <div className="flex items-center gap-3 px-3 py-2" title={fullName ? `${fullName} · ${username}` : username}>
                <div className="w-9 h-9 rounded-full bg-champagne/40 text-gold-deep grid place-items-center shrink-0">
                  <User size={16} />
                </div>
                {reveal(
                  <div className="min-w-0 leading-tight">
                    <div className="text-sm font-semibold text-zinc-800 truncate">{displayName}</div>
                    {subLine && <div className="text-xs text-zinc-400 truncate mt-0.5">{subLine}</div>}
                  </div>,
                )}
              </div>
            )
          })()}
          <button onClick={() => api.logout()} title="Cerrar sesión"
            className="flex items-center gap-3 px-3 py-2 rounded-xl text-sm text-zinc-500 hover:bg-zinc-50 hover:text-zinc-800 transition-colors w-full">
            <LogOut size={18} className="shrink-0" />
            {reveal('Cerrar sesión')}
          </button>
        </div>
      </motion.aside>
    </>
  )
}
