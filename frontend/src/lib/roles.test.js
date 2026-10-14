import { test } from 'node:test'
import assert from 'node:assert/strict'
import { canSeePage, homePath, isScoped, ROLE_LABELS } from './roles.js'

test('operador solo ve Pipeline', () => {
  assert.equal(canSeePage('/pipeline', 'operador', true), true)
  for (const p of ['/', '/leads', '/forecast', '/equipo', '/clientes', '/aprobar']) {
    assert.equal(canSeePage(p, 'operador', true), false, p)
  }
})

test('homePath: operador aterriza en Pipeline, el resto en el Dashboard', () => {
  assert.equal(homePath('operador'), '/pipeline')
  for (const r of ['admin', 'cro', 'cto', 'cco', null]) assert.equal(homePath(r), '/')
})

test('isScoped solo para operador', () => {
  assert.equal(isScoped('operador'), true)
  for (const r of ['admin', 'cro', 'cto', 'cco', null, undefined]) assert.equal(isScoped(r), false)
})

test('etiqueta del operador y roles previos intactos', () => {
  assert.equal(ROLE_LABELS.operador, 'Operador')
  assert.equal(canSeePage('/', 'cro', true), true)
  assert.equal(canSeePage('/equipo', 'admin', true), true)
})
