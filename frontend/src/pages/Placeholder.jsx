import { Mail, Send, Construction } from 'lucide-react'
import { Card } from '../components/ui'

const ICONS = { mail: Mail, send: Send }

export default function Placeholder({ icon, title }) {
  const Icon = ICONS[icon] || Construction
  return (
    <Card className="py-20 text-center text-zinc-400">
      <Icon size={34} className="mx-auto mb-3 text-zinc-300" />
      <div className="font-medium text-zinc-500">{title}</div>
      <div className="text-sm">Próximamente — le asignamos contenido pronto.</div>
    </Card>
  )
}
