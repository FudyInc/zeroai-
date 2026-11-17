import assert from 'node:assert/strict'
import test from 'node:test'
import { leadIdentity } from './leadIdentity.js'

test('nombre como título y teléfono conservado aunque exista correo', () => {
  assert.deepEqual(leadIdentity({ name: '  María   Pérez ', company: '  Piscinas  Sur ', phone: '+56 9 0000 0001', email: 'cliente@example.test' }), {
    title: 'María Pérez', company: 'Piscinas Sur', phone: '+56 9 0000 0001', email: 'cliente@example.test',
  })
})

test('números y puntuación no sustituyen un nombre ausente', () => {
  for (const name of [null, '', '   ', '56900000001', '+56 (9) 0000-0001', ' ... ', 123]) {
    assert.equal(leadIdentity({ name, company: '+56 9 0000 0001', key: 'private-contact-key' }).title, 'Sin nombre registrado')
  }
})

test('empresa real sirve de título cuando falta el nombre', () => {
  assert.deepEqual(leadIdentity({ company: '  Piscinas   Sur ', phone: '56900000001' }), {
    title: 'Piscinas Sur', company: '', phone: '56900000001', email: '',
  })
})

test('no se duplica empresa igual al nombre ni se usa número como empresa', () => {
  assert.equal(leadIdentity({ name: 'María Pérez', company: ' maría   pérez ' }).company, '')
  assert.equal(leadIdentity({ name: 'María Pérez', company: '56900000001' }).company, '')
})

test('no inventa identidad desde key ni modifica datos recibidos', () => {
  const original = Object.freeze({ name: ' 李   明 ', phone: ' 56900000001 ', key: 'opaque-key' })
  assert.equal(leadIdentity(original).title, '李 明')
  assert.equal(leadIdentity(original).phone, '56900000001')
  assert.equal(leadIdentity({ key: 'opaque-key' }).title, 'Sin nombre registrado')
  assert.equal(leadIdentity().title, 'Sin nombre registrado')
})
