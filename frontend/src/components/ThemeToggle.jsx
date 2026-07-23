import { useState } from 'react'
import { Sun, Moon } from 'lucide-react'
import { cn } from '../lib/util'

const KEY = 'zero-theme'

/* Toggle de tema — clase .dark en <html> + localStorage, sin dependencias
   (el estado inicial ya lo aplica el script inline de index.html, antes del
   primer render, para evitar el flash claro→oscuro). Dispara el evento
   'zero-theme-change' para que componentes sin token propio (ej. Badge, que
   recibe su color por prop) puedan reaccionar sin recargar la página. */
export default function ThemeToggle({ className }) {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))

  const toggle = () => {
    const next = !dark
    document.documentElement.classList.toggle('dark', next)
    localStorage.setItem(KEY, next ? 'dark' : 'light')
    window.dispatchEvent(new Event('zero-theme-change'))
    setDark(next)
  }

  return (
    <button onClick={toggle} title={dark ? 'Modo claro' : 'Modo oscuro'} aria-label="Cambiar tema"
      className={cn('p-2 rounded-lg text-zinc-500 hover:bg-zinc-100 transition-colors shrink-0', className)}>
      {dark ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  )
}
