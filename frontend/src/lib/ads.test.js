import assert from 'node:assert/strict'
import test from 'node:test'
import { budgetPace, firstOfMonthChile, money, num, todayChile, VERDICT } from './ads.js'

test('el mes se calcula en hora de Chile, no del navegador', () => {
  // 2026-12-01 02:00 UTC = 2026-11-30 23:00 en Santiago (UTC-3 en verano).
  const now = new Date('2026-12-01T02:00:00Z')
  assert.deepEqual(todayChile(now), { y: 2026, m: 11, d: 30 })
  assert.equal(firstOfMonthChile(now), '2026-11-01')
})

test('sin presupuesto no se inventa uno', () => {
  for (const b of [null, undefined, 0, -5, 'x']) assert.equal(budgetPace(1000, b), null)
})

test('ritmo del presupuesto', () => {
  const day10 = new Date('2026-11-10T15:00:00Z')   // 10 de noviembre (30 días)
  assert.deepEqual(budgetPace(30000, 100000, day10),
    { pct: 30, left: 70000, projected: 90000, state: 'ok', day: 10, daysInMonth: 30 })
  assert.equal(budgetPace(50000, 100000, day10).state, 'fast')   // proyecta 150.000
  const over = budgetPace(120000, 100000, day10)
  assert.equal(over.state, 'over')
  assert.equal(over.left, 0)
  assert.equal(over.pct, 120)
})

test('cada veredicto del backend tiene texto y color', () => {
  for (const code of ['good', 'ok', 'expensive', 'learning', 'no_results']) {
    const v = VERDICT[code]
    assert.ok(v && v.l && v.c && typeof v.hint(6000, 'CLP') === 'string', code)
  }
})

test('montos y números en formato chileno, guion si no hay dato', () => {
  assert.equal(money(6000), '$6.000')
  assert.equal(money(null), '—')
  assert.equal(num(1234.4), '1.234')
  assert.equal(num(undefined), '—')
})
