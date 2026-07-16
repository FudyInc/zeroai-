// En dev: '' → el proxy de Vite manda /api a localhost:8800.
// En prod (Vercel): definí VITE_API_URL con la URL del backend en Render.
export const BASE = import.meta.env.VITE_API_URL || ''

const TOKEN_KEY = 'zero_token'
export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = (t) => (t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY))

async function req(path, opts = {}) {
  const headers = { ...(opts.headers || {}) }
  const t = getToken()
  if (t) headers.Authorization = 'Bearer ' + t
  // El backend hoy vive detrás de un túnel gratis de ngrok — sin este header,
  // ngrok le muestra a cualquier request con pinta de navegador (Chrome, etc.)
  // una página HTML de advertencia en vez de dejar pasar la respuesta JSON real.
  // Curl/Postman no la disparan (por eso "funcionaba" al probarlo a mano) pero
  // el dashboard sí, silenciosamente: r.json() fallaba y cada panel quedaba
  // vacío. Header inofensivo si el backend deja de estar detrás de ngrok.
  headers['ngrok-skip-browser-warning'] = 'true'
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
  accounts: () => req('/api/accounts'),
  setPlan: (c, tier) =>
    req('/api/accounts/' + q(c) + '/plan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tier }) }),
  kpis: (c) => req('/api/kpis?client=' + q(c)),
  board: (c) => req('/api/board?client=' + q(c)),
  leads: (c, { group = 'todos', limit = 50, offset = 0 } = {}) =>
    req(`/api/leads?client=${q(c)}&group=${q(group)}&limit=${limit}&offset=${offset}`),
  lead: (c, k) => req('/api/leads/' + q(k) + '?client=' + q(c)),
  searchLeads: (query, limit = 20) => req(`/api/leads/search?q=${q(query)}&limit=${limit}`),
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
  optimizeCampaigns: (c) => req('/api/campaigns/optimize?client=' + q(c)),
  syncAdLeads: (c) => req('/api/campaigns/sync-leads?client=' + q(c), { method: 'POST' }),
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
  vendors: () => req('/api/vendors'),
  saveVendor: (body) =>
    req('/api/vendors', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  vendorFor: (c) => req('/api/vendor?client=' + q(c)),
  setVendor: (c, vendor_id) =>
    req('/api/vendor?client=' + q(c), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ vendor_id }) }),
  pricing: (c) => req('/api/pricing?client=' + q(c)),
  setPricing: (c, pricing) =>
    req('/api/pricing?client=' + q(c), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pricing }) }),
  knowledge: (c) => req('/api/knowledge?client=' + q(c)),
  setKnowledge: (c, knowledge) =>
    req('/api/knowledge?client=' + q(c), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ knowledge }) }),
  conversation: (c, lead, limit = 50) =>
    req(`/api/conversation?client=${q(c)}&lead=${q(lead)}&limit=${limit}`),
  pitchCompose: (body) =>
    req('/api/pitch/compose', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  pitchGenerate: (body) =>
    req('/api/pitch/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  pitchSend: (body) =>
    req('/api/pitch/send', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  usedEmails: () => req('/api/emails').then((d) => d.emails),
  authStatus: () => req('/api/auth/status'),
  login: (password) =>
    req('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }) })
      .then((d) => { setToken(d.token); return d }),
  logout: () => { setToken(null); window.location.reload() },
  metaadsAccounts: () => req('/api/metaads/accounts').then((d) => d.accounts),
  whatsappStatus: () => req('/api/whatsapp/status'),
  config: () => req('/api/config'),
  setConfig: (body) =>
    req('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  assistants: () => req('/api/assistants').then((d) => d.assistants),
  vapiNumbers: () => req('/api/vapi/numbers').then((d) => d.numbers),
  call: (body) =>
    req('/api/call', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
}
