'use strict'

const assert = require('node:assert/strict')
const { safeTypingMs } = require('./humanize')

assert.equal(safeTypingMs(1500), 1500)
assert.equal(safeTypingMs(1500.9), 1500)
assert.equal(safeTypingMs(99999), 8000)
for (const bad of [undefined, null, '1500', NaN, Infinity, -5, 0, {}, [], true]) {
  assert.equal(safeTypingMs(bad), 0)
}
console.log('humanize OK')
