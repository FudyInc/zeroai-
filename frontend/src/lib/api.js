// En dev: '' → el proxy de Vite manda /api a localhost:8800.
// En prod (Vercel): definí VITE_API_URL con la URL del backend en Render.
const BASE = import.meta.env.VITE_API_URL || ''

const TOKEN_KEY = 'zero_token'
export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = (t) => (t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY))

async function req(path, opts = {}) {
  const headers = { ...(opts.headers || {}) }
  const t = getToken()
  if (t) headers.Authorization = 'Bearer ' + t
  const r = await fetch(BASE + path, { ...opts, headers })
  if (r.status === 401) {
    setToken(null)
    window.dispatchEvent(new Event('zero-unauth'))
    throw new Error('Sesión no autorizada')
  }
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
  leads: (c, { group = 'todos', limit = 50, offset = 0 } = {}) =>
    req(`/api/leads?client=${q(c)}&group=${q(group)}&limit=${limit}&offset=${offset}`),
  lead: (c, k) => req('/api/leads/' + q(k) + '?client=' + q(c)),
  moveStage: (c, k, stage) =>
    req('/api/leads/' + q(k) + '/stage?client=' + q(c), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ stage }),
    }),
  reply: (c, k, body) =>
    req('/api/leads/' + q(k) + '/reply?client=' + q(c), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}),
    }),
  icp: (c) => req('/api/icp?client=' + q(c)).then((d) => d.icp),
  campaigns: (c) => req('/api/campaigns?client=' + q(c)),
  marketing: (c) => req('/api/marketing?client=' + q(c)),
  setMarketing: (c, body) =>
    req('/api/marketing?client=' + q(c), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  forecast: (c) => req('/api/forecast?client=' + q(c)),
  runPipeline: (body) =>
    req('/api/pipeline', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  testEmail: (to) =>
    req('/api/test-email', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ to }) }),
  simulateAgent: (body) =>
    req('/api/whatsapp/simulate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  pitchCompose: (body) =>
    req('/api/pitch/compose', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  pitchSend: (body) =>
    req('/api/pitch/send', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  authStatus: () => req('/api/auth/status'),
  login: (password) =>
    req('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }) })
      .then((d) => { setToken(d.token); return d }),
  logout: () => { setToken(null); window.location.reload() },
  config: () => req('/api/config'),
  setConfig: (body) =>
    req('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  assistants: () => req('/api/assistants').then((d) => d.assistants),
  vapiNumbers: () => req('/api/vapi/numbers').then((d) => d.numbers),
  call: (body) =>
    req('/api/call', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
}
