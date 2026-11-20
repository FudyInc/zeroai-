'use strict'
const assert = require('node:assert/strict')
const { readChatMessages } = require('./chat-history')

async function main() {
  const msg = (id, t, body, fromMe = false) => ({ id: { _serialized: id, fromMe }, t, body, type: 'chat' })
  const recent = [msg('latest', 20, 'Nuevo')]
  let pages = [[msg('earlier', 10, 'Anterior', true)], []]
  const chat = { id: { _serialized: '123456789@lid' }, msgs: { getModelsArray: () => recent } }
  global.window = { require(name) {
    if (name === 'WAWebCollections') return { Chat: { getModelsArray: () => [chat] } }
    if (name === 'WAWebChatLoadMessages') return { loadEarlierMsgs: async () => pages.shift() || [] }
    throw Error(name)
  } }
  const page = { evaluate: (fn, arg) => fn(arg) }
  const history = await readChatMessages(page, '123456789@lid', 100)
  assert.deepEqual(history.map(x => x.id), ['earlier', 'latest'])
  assert.equal(history[0].fromMe, true)
  assert.equal(history[1].body, 'Nuevo')
  assert.equal((await readChatMessages(page, '123456789@lid', 1))[0].id, 'latest')
  const rawId = { fromMe: false, remote: { user: '123456789', server: 'lid' }, id: 'ABC123', $1: 'false_123456789@lid_ABC123' }
  recent.push({ id: rawId, type: 'chat', body: 'ID de modelo vivo', t: 30 })
  assert.equal((await readChatMessages(page, '123456789@lid', 1))[0].id, 'false_123456789@lid_ABC123')
  recent.pop()
  recent.push({ id: 'true_123456789@lid_DEF456', type: 'chat', body: 'Respuesta propia', t: 31 })
  assert.equal((await readChatMessages(page, '123456789@lid', 1))[0].fromMe, true)
  recent.pop()
  // Anuncio de clic a WhatsApp: los avisos del sistema no son el último mensaje.
  recent.push({ id: 'false_123456789@lid_TPL1', type: 'notification_template', body: '', t: 32 })
  recent.push({ id: 'false_123456789@lid_E2E1', type: 'e2e_notification', body: '', t: 33 })
  assert.equal((await readChatMessages(page, '123456789@lid', 1))[0].id, 'latest')
  assert.deepEqual((await readChatMessages(page, '123456789@lid', 100)).map(x => x.type), ['chat'])
  recent.pop(); recent.pop()
  await assert.rejects(readChatMessages(page, '999999999@lid', 100), /Chat no encontrado/)
  pages = [[msg('latest', 20, 'Nuevo')]]
  assert.equal((await readChatMessages(page, '123456789@lid', 100)).length, 1)
  recent.push({ type: 'chat', body: 'sin identidad' })
  await assert.rejects(readChatMessages(page, '123456789@lid', 100), /id estable/)
  delete global.window
}
main().catch(error => { console.error(error); process.exitCode = 1 })
