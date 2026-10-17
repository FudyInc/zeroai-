// Qué página ve cada rol — fuente única, usada por Sidebar.jsx (nav) y
// CommandPalette (Cmd+K), para que ambos coincidan siempre. Esto es solo UX:
// la barrera real (403) ya vive en el backend (api.py::_ROLE_ALLOWED). Un
// path sin entrada acá, o con array vacío, es admin-only (fail closed, igual
// que el backend). Asignado por Diego (2026-07-17):
//   - "cro" (Lucas): Dashboard, Pipeline, Forecast, Clientes, Campañas,
//     Vender, Finanzas (exclusiva — ni "cto" la ve).
//   - "cto" (Alejandro): Dashboard, Leads, Pipeline, Forecast.
//   - "cco" (Maureen, 2026-07-20): contenido/comunicaciones — Dashboard,
//     Pipeline (revisar/editar borradores de outreach), Vender, Campañas,
//     WhatsApp (tono, ficha, precios). Nada de Forecast/Clientes/Finanzas ni
//     Configuración.
//   - Llamadas/Arquitectura/Configuración: solo admin. Agentes: admin + operador
//     (el operador solo ve el panel de Instagram, ver pages/Agentes.jsx).
//   - Equipo (2026-07-20): SOLO admin (Diego) — quién tiene cuenta, qué rol,
//     quién está conectado. El backend ya lo exige (sin entrada en
//     _ROLE_ALLOWED, fail-closed); esto es solo para ocultar el link.
//   - Funciones (2026-07-22): SOLO admin — corre código Python arbitrario
//     (sandboxed en Docker) contra leads reales de un cliente. Mismo
//     fail-closed que el resto de las páginas admin-only.
//   - Ciclo (2026-09-09): SOLO admin — muestra la cola de trabajo autónomo, la
//     telemetría de los agentes y la auditoría diaria. Es interna de la agencia,
//     no del cliente. Antes esta ruta era /conductor y además lanzaba sesiones
//     del CLI `claude`; esa mitad se sacó por no usarse (ver pages/Ciclo.jsx).
//   - Por aprobar (2026-08-04): admin + cro/cto/cco. Es la bandeja de
//     borradores que dejaron las corridas automáticas; revisar y enviar
//     outreach ya es trabajo de esos tres roles (mismo criterio que el
//     POST /api/leads/{key}/send que ya tenían).
//   - "operador" (Stefano): rol con alcance por cliente — Leads, Pipeline y
//     Agentes (solo Instagram; más el modal "Buscar leads", que no es página).
//     Leads (Diego, 2026-10-16): GET /api/leads ya era suyo y _require_client
//     lo acota a sus clientes — no abre nada nuevo en el backend. Ve únicamente los clientes que
//     Diego le asigna en Equipo; la barrera real es el backend (404 fuera de
//     alcance), esto evita mostrarle o pedirle nada de otros clientes.
//   - Preferencias (2026-07-23): cro/cto/cco (y admin) — es personal (tema, por
//     ahora), 100% cliente/localStorage, nada sensible ni de la agencia. El
//     "operador" NO la tiene (decisión de Diego: Leads, Pipeline y Agentes por ahora).
export const PAGE_ROLES = {
  '/': ['cro', 'cto', 'cco'],
  '/leads': ['cto', 'operador'],
  '/pipeline': ['cro', 'cto', 'cco', 'operador'],
  '/forecast': ['cro', 'cto'],
  '/vender': ['cro', 'cco'],
  '/campanas': ['cro', 'cco'],
  '/clientes': ['cro'],
  '/finanzas': ['cro'],
  '/agentes': ['operador'],
  '/llamadas': [],
  '/whatsapp': ['cco'],
  '/arquitectura': [],
  '/config': [],
  '/equipo': [],
  '/funciones': [],
  '/avances': [],
  '/ciclo': [],
  '/aprobar': ['cro', 'cto', 'cco'],
  '/preferencias': ['cro', 'cto', 'cco'],
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
export const ROLE_LABELS = { admin: 'CEO', cro: 'CRO', cto: 'CTO', cco: 'CCO', operador: 'Operador' }

// Roles que solo operan sobre los clientes que se les asignaron. Para ellos la UI
// no lista, sugiere ni deja escribir clientes fuera de su alcance.
export const SCOPED_ROLES = ['operador']
export const isScoped = (role) => SCOPED_ROLES.includes(role)

// Dónde aterriza cada rol: el operador no ve el Dashboard (muestra todos los clientes).
export const homePath = (role) => (isScoped(role) ? '/pipeline' : '/')
