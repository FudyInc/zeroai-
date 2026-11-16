'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const { sendGuarded } = require('./send-guard')

test('intervención durante el indicador de escritura cancela el envío', async () => {
  let latest = 'incoming'; let sends = 0
  await assert.rejects(sendGuarded({ expected_last_id: 'incoming', expires_at: 200 }, {
    now: () => 100, typing: async () => { latest = 'manual' },
    latestId: async () => latest, send: async () => { sends++; return 'sent' },
  }), /chat cambió/)
  assert.equal(sends, 0)
})
test('vencimiento durante escritura también cancela sin enviar', async () => {
  let now = 100; let sends = 0
  await assert.rejects(sendGuarded({ expected_last_id: 'incoming', expires_at: 200 }, {
    now: () => now, typing: async () => { now = 201 }, latestId: async () => 'incoming',
    send: async () => { sends++; return 'sent' },
  }), /antiguo/)
  assert.equal(sends, 0)
})
test('chat verificado envía una sola vez y devuelve confirmación', async () => {
  let sends = 0
  const result = await sendGuarded({ expected_last_id: 'incoming', expires_at: 200 }, {
    now: () => 100, typing: async () => {}, latestId: async () => 'incoming',
    send: async () => { sends++; return { id: 'sent' } },
  })
  assert.deepEqual(result, { id: 'sent' }); assert.equal(sends, 1)
})
test('lectura fallida impide enviar y conserva el error', async () => {
  let sends = 0
  await assert.rejects(sendGuarded({ expected_last_id: 'incoming', expires_at: 200 }, {
    now: () => 100, typing: async () => {}, latestId: async () => { throw Error('lectura fallida') },
    send: async () => { sends++ },
  }), /lectura fallida/)
  assert.equal(sends, 0)
})
