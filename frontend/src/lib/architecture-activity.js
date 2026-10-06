// La ventana operativa excluye fixtures antiguas; el historial almacenado no cambia.
export function architectureActivity(data) {
  const recientes = (data?.recientes || []).filter(e => {
    const engine = String(e.engine || '')
    return !/mock|scriptedbackend|boombackend/i.test(engine)
  })
  const groups = new Map()
  for (const e of recientes) {
    if (!groups.has(e.agent)) groups.set(e.agent, [])
    groups.get(e.agent).push(e)
  }
  const agentes = [...groups].map(([agent, events]) => {
    const times = events.map(e => Number(e.ms) || 0).sort((a, b) => a - b)
    return {
      agent, corridas: events.length, errores: events.filter(e => e.status === 'error').length,
      engines: [...new Set(events.map(e => e.engine).filter(Boolean))],
      ms_mediana: times[Math.floor(times.length / 2)],
    }
  })
  return { recientes, agentes, eventos: recientes.length, max_eventos: data?.max_eventos || 200 }
}
