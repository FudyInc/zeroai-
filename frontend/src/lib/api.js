// En dev: '' → el proxy de Vite manda /api a localhost:8800.
// En prod (Vercel): definí VITE_API_URL con la URL del backend en Render.
const BASE = import.meta.env.VITE_API_URL || ''

async function req(path, opts) {
  const url = BASE + path
  const r = await fetch(url, opts)
  if (!r.ok) {
    let msg
    try { msg = (await r.json()).detail } catch { msg = r.statusText }
    throw new Error(msg || 'HTTP ' + r.status)
  }
  return r.json()
}
const q = encodeURIComponent

export const api = {
  clients: () => req('/api/clients').then((d) => d.clients),
  kpis: (c) => req('/api/kpis?client=' + q(c)),
  board: (c) => req('/api/board?client=' + q(c)),
  leads: (c) => req('/api/leads?client=' + q(c)).then((d) => d.leads),
  lead: (c, k) => req('/api/leads/' + q(k) + '?client=' + q(c)),
  moveStage: (c, k, stage) =>
    req('/api/leads/' + q(k) + '/stage?client=' + q(c), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ stage }),
    }),
  forecast: (c) => req('/api/forecast?client=' + q(c)),
  runPipeline: (body) =>
    req('/api/pipeline', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  config: () => req('/api/config'),
  setConfig: (body) =>
    req('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  assistants: () => req('/api/assistants').then((d) => d.assistants),
  vapiNumbers: () => req('/api/vapi/numbers').then((d) => d.numbers),
  call: (body) =>
    req('/api/call', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
}
