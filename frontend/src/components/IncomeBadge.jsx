import { Badge } from './ui'

/* Marca de renta de un lead de Instagram Ads. `income_ok` lo decide el backend
   contra el umbral del cliente; acá solo se dibuja (null = sin marca). */
export default function IncomeBadge({ ok }) {
  if (ok === true) return <Badge color="#16a34a">Sobre umbral</Badge>
  if (ok === false) return <Badge color="#d97706">Bajo umbral</Badge>
  return null
}
