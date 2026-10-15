'use strict'

const test = require('node:test')
const assert = require('node:assert')
const { actsFor } = require('./account-scope')

test('the default bridge may act for the business it is connected to', () => {
  // The regression: LosetasChile runs on the bridge started without
  // WHATSAPP_WEB_CLIENT_ID, so a strict equality check answered every catalog
  // PDF request with 403 while the message itself went to human review.
  assert.strictEqual(actsFor('', 'losetaschile'), true)
  assert.strictEqual(actsFor(undefined, 'losetaschile'), true)
})

test('a bridge named for the business may act for it', () => {
  assert.strictEqual(actsFor('losetaschile', 'losetaschile'), true)
})

test('a bridge named for another business may not', () => {
  assert.strictEqual(actsFor('pooledge', 'losetaschile'), false)
  assert.strictEqual(actsFor('zeroai', 'losetaschile'), false)
})

test('no business named means nothing is allowed', () => {
  assert.strictEqual(actsFor('', ''), false)
  assert.strictEqual(actsFor('losetaschile', ''), false)
  assert.strictEqual(actsFor('', undefined), false)
})
