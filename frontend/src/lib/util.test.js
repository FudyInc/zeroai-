import assert from 'node:assert/strict'
import test from 'node:test'
import { leadRoute } from './util.js'

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
