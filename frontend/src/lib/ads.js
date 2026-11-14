/* Helpers de la pantalla de anuncios (Campañas): formato de montos, el mes en
   hora de Chile, textos del veredicto y el ritmo de gasto del presupuesto.
   Sin React: se prueban con node --test. Las reglas del veredicto viven en el
   backend (zero/config.py ADS_VERDICT_*); aquí solo se dibujan. */

export const finite = (n) => n != null && n !== '' && Number.isFinite(Number(n))
export const num = (n) => (finite(n) ? Math.round(Number(n)).toLocaleString('es-CL') : '—')

// Moneda la trae la API; si el código no es válido, cae a número con el código al lado.
export function money(n, currency) {
  if (!finite(n)) return '—'
  const cur = currency || 'CLP'
  try {
    return new Intl.NumberFormat('es-CL', { style: 'currency', currency: cur, maximumFractionDigits: cur === 'CLP' ? 0 : 2 }).format(n)
  } catch {
    return `${Math.round(n).toLocaleString('es-CL')} ${cur}`
  }
}

// Fecha de hoy en Santiago como {y, m, d}: el mes de Meta es el de la cuenta (Chile),
// no el del navegador.
export function todayChile(now = new Date()) {
  const [y, m, d] = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Santiago', year: 'numeric', month: '2-digit', day: '2-digit' })
    .format(now).split('-').map(Number)
  return { y, m, d }
}

export function firstOfMonthChile(now = new Date()) {
  const { y, m } = todayChile(now)
  return `${y}-${String(m).padStart(2, '0')}-01`
}

/* Ritmo del presupuesto mensual. Devuelve null sin presupuesto (no se inventa).
   - pct: porcentaje gastado (puede pasar de 100).
   - left: lo que queda (0 si ya se pasó).
   - projected: gasto estimado a fin de mes si sigue al ritmo actual.
   - state: 'over' (ya se pasó), 'fast' (al ritmo actual se pasará), 'ok'. */
export function budgetPace(spent, budget, now = new Date()) {
  if (!finite(budget) || Number(budget) <= 0) return null
  const s = Math.max(Number(spent) || 0, 0)
  const b = Number(budget)
  const { y, m, d } = todayChile(now)
  const daysInMonth = new Date(Date.UTC(y, m, 0)).getUTCDate()
  const projected = Math.round((s / d) * daysInMonth)
  const state = s > b ? 'over' : projected > b ? 'fast' : 'ok'
  return { pct: Math.round((s / b) * 100), left: Math.max(b - s, 0), projected, state, day: d, daysInMonth }
}

// Textos y colores del veredicto que calcula el backend (`verdict.code`).
export const VERDICT = {
  good: { l: 'Va bien', c: '#16a34a', hint: (t, cur) => `Cada consulta cuesta ${t ? money(t, cur) + ' o menos' : 'poco'}. Conviene mantenerlo.` },
  ok: { l: 'Aceptable', c: '#d97706', hint: (t, cur) => `Las consultas salen un poco sobre ${t ? money(t, cur) : 'el objetivo'}. Prueba mejorar el texto o la imagen.` },
  expensive: { l: 'Caro', c: '#e11d48', hint: () => 'Cada consulta sale cara. Considera pausarlo o cambiar el texto y la imagen.' },
  learning: { l: 'Aprendiendo', c: '#64748b', hint: () => 'Lleva poco gasto: Meta todavía está buscando a quién mostrarlo. Dale unos días.' },
  no_results: { l: 'Sin resultados', c: '#e11d48', hint: () => 'Ya gastó y nadie ha consultado. Revisa el anuncio o mueve ese dinero a uno que funcione.' },
}
