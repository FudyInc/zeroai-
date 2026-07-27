import { Sun, Moon } from 'lucide-react'
import { cn } from '../lib/util'
import { useIsDark, setTheme } from '../lib/theme'

/* Flip rápido claro↔oscuro desde el header (alcanzable en cualquier
   pantalla). Elige explícito light/dark — "Sistema" queda para el selector
   de 3 opciones en Preferencias, no acá. */
export default function ThemeToggle({ className }) {
  const dark = useIsDark()
  return (
    <button onClick={() => setTheme(dark ? 'light' : 'dark')} title={dark ? 'Modo claro' : 'Modo oscuro'} aria-label="Cambiar tema"
      className={cn('p-2 rounded-lg text-zinc-500 hover:bg-zinc-100 transition-colors shrink-0', className)}>
      {dark ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  )
}
