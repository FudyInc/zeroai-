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

// Una campaña puede conservar ACTIVE en Meta después del fin de sus conjuntos.
// El backend determina su vigencia; el anuncio además debe seguir activo.
export function visiblePaidAds(items, campaigns, scope = 'active') {
  if (!campaigns || scope === 'history') return items
  const activeCampaigns = new Map(campaigns.filter((c) => c.status === 'active').map((c) => [
    String(c.id), Array.isArray(c.active_ad_ids) ? new Set(c.active_ad_ids.map(String)) : null,
  ]))
  return items.filter((ad) => {
    const campaignId = String(ad.campaign_id)
    if (!activeCampaigns.has(campaignId) || String(ad.status).toLowerCase() !== 'active') return false
    const activeAdIds = activeCampaigns.get(campaignId)
    return activeAdIds === null || activeAdIds.has(String(ad.ad_id))
  })
}

// Prioridad al abrir la pantalla. Usa los mismos totales y objetivo que el resumen.
export function campaignReview(summary, now = new Date()) {
  if (summary.error) return { title: 'Vuelve a consultar Meta', detail: 'Falló la lectura de la cuenta. Actualiza los datos para volver a intentarlo.' }
  if (summary.source !== 'live') return { title: 'Conecta tu cuenta de Meta', detail: 'Asigna la cuenta publicitaria de este negocio para consultar sus campañas.' }
  const pace = budgetPace(summary.spent_clp, summary.budget_clp, now)
  if (pace?.state === 'over') return { title: 'Revisa el gasto del mes', detail: `La inversión supera tu presupuesto mensual en ${money(summary.spent_clp - summary.budget_clp)}.` }
  if (!summary.active) return { title: 'Sin campañas en circulación', detail: 'Cuando Meta registre una campaña activa, podrás pedirle al agente que la revise.' }
  if (!pace) return { title: 'Define cuánto quieres invertir', detail: 'Con un presupuesto mensual podrás ver cuánto queda y si el gasto va demasiado rápido.' }
  if (pace.state === 'fast') return { title: 'Revisa el ritmo de gasto', detail: `Si sigue el ritmo actual, la inversión del mes llegaría a ${money(pace.projected)} frente a ${money(summary.budget_clp)} previstos.` }
  if (summary.leads > 0 && summary.cpl_clp > summary.good_cpl_clp) return { title: 'Revisa el costo por consulta', detail: `Este mes cada consulta costó en promedio ${money(summary.cpl_clp)}. El objetivo es ${money(summary.good_cpl_clp)}.` }
  return { title: 'Sigue el rendimiento de tus campañas', detail: summary.leads ? 'El gasto va dentro del ritmo previsto y el costo promedio por consulta está dentro del objetivo.' : 'Todavía no se registran consultas este mes. Puedes revisar los anuncios que están circulando.' }
}
