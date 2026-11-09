import assert from 'node:assert/strict'
import test from 'node:test'
import { clientLabel, setClientLabels } from './clientLabels.js'

test('clientLabel devuelve la etiqueta o el id si no hay', () => {
  setClientLabels({ losetaschile: 'Pooledge' })
  assert.equal(clientLabel('losetaschile'), 'Pooledge')
  assert.equal(clientLabel('acme'), 'acme')
})

test('clientLabel deja pasar ids vacíos', () => {
  setClientLabels({ losetaschile: 'Pooledge' })
  assert.equal(clientLabel(''), '')
  assert.equal(clientLabel(undefined), undefined)
  assert.equal(clientLabel(null), null)
})

test('labels ausente o inválido (backend viejo) muestra el id', () => {
  for (const bad of [undefined, null, [], 'x']) {
    setClientLabels({ losetaschile: 'Pooledge' })
    setClientLabels(bad)
    assert.equal(clientLabel('losetaschile'), 'losetaschile')
  }
})
