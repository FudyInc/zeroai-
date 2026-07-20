// Qué página ve cada rol — fuente única, usada por Sidebar.jsx (nav) y
// CommandPalette (Cmd+K), para que ambos coincidan siempre. Esto es solo UX:
// la barrera real (403) ya vive en el backend (api.py::_ROLE_ALLOWED). Un
// path sin entrada acá, o con array vacío, es admin-only (fail closed, igual
// que el backend). Asignado por Diego (2026-07-17):
//   - "cro" (Lucas): Dashboard, Pipeline, Forecast, Clientes, Campañas,
//     Vender, Finanzas (exclusiva — ni "cto" la ve).
//   - "cto" (Alejandro): Dashboard, Leads, Pipeline, Forecast.
//   - Agentes/Llamadas/WhatsApp/Arquitectura/Configuración: solo admin.
//   - Equipo (2026-07-20): SOLO admin (Diego) — quién tiene cuenta, qué rol,
//     quién está conectado. El backend ya lo exige (sin entrada en
//     _ROLE_ALLOWED, fail-closed); esto es solo para ocultar el link.
export const PAGE_ROLES = {
  '/': ['cro', 'cto'],
  '/leads': ['cto'],
  '/pipeline': ['cro', 'cto'],
  '/forecast': ['cro', 'cto'],
  '/vender': ['cro'],
  '/campanas': ['cro'],
  '/clientes': ['cro'],
  '/finanzas': ['cro'],
  '/agentes': [],
  '/llamadas': [],
  '/whatsapp': [],
  '/arquitectura': [],
  '/config': [],
  '/equipo': [],
}

// `authEnabled=false` (sin cuentas dadas de alta, mock/dev) → sin restricción,
// mismo comportamiento de siempre. `role=null` con auth activo → sin rol
// asignado, fail closed también acá (nada le funcionaría del lado del API).
export function canSeePage(path, role, authEnabled) {
  if (!authEnabled) return true
  if (role === 'admin') return true
  if (!role) return false
  return (PAGE_ROLES[path] || []).includes(role)
}

// Solo para mostrar — el rol real (permisos) sigue siendo "admin"/"cro"/"cto"
// en todo el backend; esto es la etiqueta que ve el humano en el sidebar.
export const ROLE_LABELS = { admin: 'CEO', cro: 'CRO', cto: 'CTO' }
