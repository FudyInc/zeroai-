import { useEffect, useState } from 'react'

// Tema con 3 estados: 'light' | 'dark' | null (null = "Sistema", sigue
// prefers-color-scheme). Nada en localStorage = Sistema — mismo criterio que
// ya aplica el script inline de index.html antes del primer render.
const KEY = 'zero-theme'

export const getStoredTheme = () => localStorage.getItem(KEY) // 'light' | 'dark' | null

const systemPrefersDark = () => window.matchMedia('(prefers-color-scheme: dark)').matches

const resolvedIsDark = (stored) => (stored ? stored === 'dark' : systemPrefersDark())

const applyTheme = (stored) => {
  document.documentElement.classList.toggle('dark', resolvedIsDark(stored))
}

// value: 'light' | 'dark' | 'system'
export function setTheme(value) {
  if (value === 'system') localStorage.removeItem(KEY)
  else localStorage.setItem(KEY, value)
  applyTheme(getStoredTheme())
  window.dispatchEvent(new Event('zero-theme-change'))
}

// Solo lee si hoy se ve oscuro o claro (para componentes que no tienen
// token propio, ej. Badge — color por prop, sin CSS var que heredar).
export function useIsDark() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))
  useEffect(() => {
    const onChange = () => setDark(document.documentElement.classList.contains('dark'))
    window.addEventListener('zero-theme-change', onChange)
    // Si el usuario eligió "Sistema", un cambio de prefers-color-scheme en
    // caliente (ej. el SO cambia de tema solo de noche) debe reflejarse sin
    // recargar la página.
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onSystemChange = () => { if (!getStoredTheme()) { applyTheme(null); onChange() } }
    mq.addEventListener('change', onSystemChange)
    return () => {
      window.removeEventListener('zero-theme-change', onChange)
      mq.removeEventListener('change', onSystemChange)
    }
  }, [])
  return dark
}

// Para el selector de 3 opciones en Preferencias: 'light' | 'dark' | 'system'.
export function useThemePreference() {
  const [pref, setPref] = useState(() => getStoredTheme() || 'system')
  useEffect(() => {
    const onChange = () => setPref(getStoredTheme() || 'system')
    window.addEventListener('zero-theme-change', onChange)
    return () => window.removeEventListener('zero-theme-change', onChange)
  }, [])
  return [pref, setTheme]
}
