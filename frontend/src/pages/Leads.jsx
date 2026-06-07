import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { STAGES, ORDER, scoreColor } from '../lib/util'
import { Card } from '../components/ui'
import { useApp } from '../App'
import { NoClient } from './Dashboard'

export default function Leads() {
  const { client, openLead } = useApp()
  const qc = useQueryClient()
  const { data: leads = [] } = useQuery({ queryKey: ['leads', client], queryFn: () => api.leads(client), enabled: !!client })
  if (!client) return <NoClient />

  const move = async (k, stage) => { await api.moveStage(client, k, stage); qc.invalidateQueries() }

  return (
    <Card className="overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-zinc-50 text-zinc-500 text-left text-xs uppercase tracking-wide">
          <tr>{['Empresa', 'Cargo', 'Contacto', 'Score', 'Etapa'].map((h) => <th key={h} className="px-5 py-3 font-medium">{h}</th>)}</tr>
        </thead>
        <tbody>
          {leads.map((r) => (
            <tr key={r.key} onClick={() => openLead(r.key)} className="border-t border-zinc-100 hover:bg-zinc-50 cursor-pointer transition-colors">
              <td className="px-5 py-3 font-medium">{r.company}</td>
              <td className="px-5 py-3 text-zinc-500">{r.role || '—'}</td>
              <td className="px-5 py-3 text-zinc-500">{r.email || r.phone || '—'}</td>
              <td className="px-5 py-3 font-extrabold tabular-nums" style={{ color: scoreColor(r.score) }}>{r.score ?? '—'}</td>
              <td className="px-5 py-3" onClick={(e) => e.stopPropagation()}>
                <select value={r.stage} onChange={(e) => move(r.key, e.target.value)}
                  className="text-xs border border-zinc-200 rounded-lg px-2 py-1 bg-zinc-50 text-zinc-600 outline-none focus:ring-2 focus:ring-emerald-200">
                  {ORDER.map((s) => <option key={s} value={s}>{STAGES[s].l}</option>)}
                </select>
              </td>
            </tr>
          ))}
          {leads.length === 0 && <tr><td colSpan={5} className="px-5 py-10 text-center text-zinc-400">Sin leads. Usá “Buscar leads”.</td></tr>}
        </tbody>
      </table>
    </Card>
  )
}
