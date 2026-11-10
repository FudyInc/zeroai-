'use strict'

const assert = require('node:assert/strict')
const { stableMessageId } = require('./message-id')

const serialized = 'false_111111111111111@lid_3A0F00AABBCCDDEEFF00'
assert.equal(stableMessageId({ _serialized: serialized }), serialized)
assert.equal(stableMessageId({ $1: serialized, fromMe: false, id: 'X' }), serialized)
assert.equal(stableMessageId({ fromMe: false, remote: '111111111111111@lid', id: '3A0F00AABBCCDDEEFF00' }), serialized)
assert.equal(stableMessageId({ fromMe: false, remote: { _serialized: '111111111111111@lid' }, id: '3A0F00AABBCCDDEEFF00' }), serialized)
assert.equal(stableMessageId(serialized), serialized)
for (const bad of [undefined, null, '', '[object Object]', {}, { $1: '[object Object]' },
  { _serialized: '[object Object]' }, { fromMe: false, remote: '', id: 'X' }, 42]) {
  assert.equal(stableMessageId(bad), null)
}
const a = stableMessageId({ fromMe: false, remote: '111111111111111@lid', id: 'AAA1' })
const b = stableMessageId({ fromMe: false, remote: '111111111111111@lid', id: 'AAA2' })
assert.notEqual(a, b)
console.log('stable message id OK')
