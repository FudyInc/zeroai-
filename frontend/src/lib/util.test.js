import assert from 'node:assert/strict'
import test from 'node:test'
import { LANE, leadRoute } from './util.js'

const event = (detail, ts = '2026-09-01T12:00:00Z') => ({ event: 'stage', detail, ts })

test('salidas solo completan pasos acreditados por el historial', () => {
  for (const [stage, from, reached] of [
    ['lost', 'contacted', 2],
    ['lost', 'meeting', 5],
    ['lost', 'won', 6],
    ['disqualified', 'new', 0],
    ['disqualified', 'contacted', 2],
  ]) {
    const route = leadRoute({ stage, history: [event(`${from} → ${stage} (motivo)`)] })
    assert.equal(route.reached, reached)
    assert.equal(route.steps.filter(s => s.done).length, reached + 1)
    assert.ok(route.steps.every(s => !s.current))
    assert.ok(route.exit)
  }
})

test('salidas sin historial no inventan progreso', () => {
  for (const stage of ['lost', 'disqualified']) {
    for (const history of [undefined, {}, [], [null, event(null)]]) {
      const route = leadRoute({ stage, history })
      assert.equal(route.reached, -1)
      assert.equal(route.pct, 0)
      assert.ok(route.steps.every(s => !s.done && !s.at))
    }
  }
})

test('la etapa actual manda tras retroceder y las fechas no se interpolan', () => {
  const route = leadRoute({ stage: 'qualified', history: [
    event('new → meeting'), event('meeting → qualified', 'fecha inválida'),
  ], outreach: { status: 'draft' } })
  assert.equal(route.reached, 1)
  assert.equal(route.steps[1].current, true)
  assert.equal(route.steps[5].done, false)
  assert.ok(route.steps.every(s => !s.at))
  assert.equal(route.days, null)
  assert.equal(route.pendingApproval, true)
})

test('datos ausentes o etapa desconocida mantienen el carril apagado', () => {
  for (const lead of [null, {}, { stage: 'desconocida' }, { stage: 'toString' }]) {
    const route = leadRoute(lead)
    assert.equal(route.exit, null)
    assert.ok(route.steps.every(s => !s.done))
  }
})

/* --- El carril no puede crecer a espaldas de nadie --------------------------------
 * Si alguien mete `disqualified` o `lost` en LANE, la pantalla vuelve a afirmar que
 * descartar es avanzar. Es el error que este trabajo existe para no cometer, así que
 * queda clavado acá y no en un comentario. */
test('el carril son 7 pasos y las salidas no están entre ellos', () => {
  assert.deepEqual(LANE,
    ['new', 'qualified', 'contacted', 'nurturing', 'replied', 'meeting', 'won'])
  assert.ok(!LANE.includes('disqualified'))
  assert.ok(!LANE.includes('lost'))
})

test('un detail sin destino legible no acredita fecha ni revienta', () => {
  for (const detail of ['contacted', 'qualified → ', '', null, 42]) {
    const route = leadRoute({ stage: 'contacted', history: [event(detail)] })
    assert.equal(route.reached, 2)          // la manda `lead.stage`, no el historial
    assert.ok(route.steps.every((s) => !s.at), `acreditó fecha con detail ${detail}`)
  }
})

test('un detail sin origen pero con destino sí acredita su fecha', () => {
  /* "→ contacted" está mal formado, pero el destino se lee y basta: el lead llegó
     a esa etapa. Descartar el evento entero sería perder un dato que sí está. */
  const route = leadRoute({ stage: 'contacted', history: [event('→ contacted')] })
  assert.ok(route.steps[2].at)
})

test('`pct` se queda siempre dentro del riel', () => {
  const casos = [null, {}, { stage: 'new' }, { stage: 'won' }, { stage: 'desconocida' },
    { stage: 'lost', history: [event('meeting → won'), event('won → lost')] }]
  for (const lead of casos) {
    const { pct } = leadRoute(lead)
    assert.ok(Number.isFinite(pct) && pct >= 0 && pct <= 100, `pct fuera de rango: ${pct}`)
  }
})

test('una fecha futura no produce una antigüedad negativa', () => {
  const route = leadRoute({ stage: 'qualified', history: [event('new → qualified', '2099-01-01T00:00:00Z')] })
  assert.equal(route.days, null)
})

test('la antigüedad sale de la ÚLTIMA entrada a la etapa actual', () => {
  /* El recorrido no es monótono: si el lead volvió a `contacted`, lo que se muestra
     es cuánto lleva en esta pasada, no en la primera. */
  const route = leadRoute({ stage: 'contacted', history: [
    event('new → contacted', '2020-01-01T00:00:00Z'),
    event('contacted → replied', '2020-02-01T00:00:00Z'),
    event('replied → contacted', new Date(Date.now() - 3 * 86400000).toISOString()),
  ] })
  assert.equal(route.days, 3)
})
