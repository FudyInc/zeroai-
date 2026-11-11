'use strict'

const assert = require('node:assert/strict')
const test = require('node:test')
const { sendInboxReply, UNCONFIRMED } = require('./inbox-reply')

const LID = '111111111111111@lid'

function deps({ confirmed = { id: 'true_x@lid_ABC', ack: 1 }, phone = '56900000000', fail = null } = {}) {
  const calls = []
  return {
    calls,
    sendAndConfirm: async (...args) => { calls.push(args); if (fail) throw fail; return confirmed },
    resolvePhone: async () => phone,
    now: () => 1700000000,
  }
}

test('envío confirmado: 200 con el mensaje y el teléfono real', async () => {
  const d = deps()
  const out = await sendInboxReply(LID, 'Hola', d)
  assert.equal(out.status, 200)
  assert.equal(out.body.confirmed, true)
  assert.equal(out.body.phone, '56900000000')
  assert.deepEqual(out.body.message, { id: 'true_x@lid_ABC', body: 'Hola', type: 'chat', fromMe: true, ack: 1, timestamp: 1700000000, author: null })
  const [chatId, text, options, matches, kind, body] = d.calls[0]
  assert.equal(chatId, LID); assert.equal(text, 'Hola'); assert.deepEqual(options, {})
  assert.equal(kind, 'chat'); assert.equal(body, 'Hola')
  assert.equal(matches({ type: 'chat', body: 'Hola' }), true)
  assert.equal(matches({ type: 'chat', body: 'Otro' }), false)
  assert.equal(matches({ type: 'image', body: 'Hola' }), false)
})

test('sin confirmación: 202, sin reintento y con aviso de revisar el chat', async () => {
  const d = deps({ confirmed: null })
  const out = await sendInboxReply(LID, 'Hola', d)
  assert.equal(out.status, 202)
  assert.equal(out.body.confirmed, false)
  assert.equal(out.body.message, null)
  assert.equal(out.body.warning, UNCONFIRMED)
  assert.equal(d.calls.length, 1)
})

test('teléfono no resoluble o inválido: null, sin romper el envío', async () => {
  for (const phone of [null, 'abc', '123']) {
    const out = await sendInboxReply(LID, 'Hola', deps({ phone }))
    assert.equal(out.status, 200)
    assert.equal(out.body.phone, null)
  }
  const out = await sendInboxReply(LID, 'Hola', { ...deps(), resolvePhone: async () => { throw new Error('x') } })
  assert.equal(out.body.phone, null)
})

test('un error real del envío se propaga (la ruta responde 502)', async () => {
  await assert.rejects(sendInboxReply(LID, 'Hola', deps({ fail: new Error('caído') })), /caído/)
})
