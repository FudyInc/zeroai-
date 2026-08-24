import { motion } from 'framer-motion'
import { Sun, Moon, Monitor } from 'lucide-react'
import { Card, SectionTitle } from '../components/ui'
import { Segmented } from '../components/Segmented'
import { useThemePreference } from '../lib/theme'
import { rise, surface } from '../lib/motion'

const THEME_OPTIONS = [
  { value: 'light', label: 'Claro' },
  { value: 'dark', label: 'Oscuro' },
  { value: 'system', label: 'Sistema' },
]

const THEME_ICON = { light: Sun, dark: Moon, system: Monitor }

/* Preferencias PERSONALES (por dispositivo, vía localStorage) — distinto de
   Configuración (integraciones/API keys de la agencia, admin-only). Cualquier
   rol la ve: no hay nada sensible acá, solo cómo cada quien quiere ver su
   propio dashboard. Hoy solo Tema; el próximo candidato natural (idioma)
   queda pendiente — el dashboard no tiene infraestructura de i18n todavía,
   es su propio proyecto, no un campo más acá. */
export default function Preferencias() {
  const [theme, setTheme] = useThemePreference()
  const Icon = THEME_ICON[theme] || Monitor

  return (
    <motion.div className="space-y-5 max-w-xl" initial="hidden" animate="show" variants={rise}>
      <motion.div variants={surface}>
        <Card className="p-6">
          <div className="flex items-center gap-2 mb-1">
            <Icon size={16} className="text-gold-deep" />
            <SectionTitle>Tema</SectionTitle>
          </div>
          <div className="text-xs text-zinc-400 mb-4">
            Solo afecta a este dispositivo/navegador. "Sistema" sigue lo que tengas configurado en tu SO.
          </div>
          <Segmented options={THEME_OPTIONS} value={theme} onChange={setTheme} />
        </Card>
      </motion.div>
    </motion.div>
  )
}
