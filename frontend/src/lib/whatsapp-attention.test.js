import test from 'node:test'
import assert from 'node:assert/strict'
import { attentionOf, handoffKey, humanChats, inboxNavigationKey, unseenHumanRequests } from './whatsapp-attention.js'

test('una alerta repetida y un cambio de cuenta vuelven a aplicar el destino de la bandeja', () => {
  const first = inboxNavigationKey('losetaschile', '56911111111', 'route-a', 'chat:lead')
  assert.equal(first, inboxNavigationKey('losetaschile', '56911111111', 'route-a', 'chat:lead'))
  assert.notEqual(first, inboxNavigationKey('losetaschile', '56911111111', 'route-b', 'chat:lead'))
  assert.notEqual(first, inboxNavigationKey('otro', '56911111111', 'route-a', 'chat:lead'))
  assert.notEqual(first, inboxNavigationKey('losetaschile', '56922222222', 'route-a', 'chat:lead'))
  assert.notEqual(first, inboxNavigationKey('losetaschile', '56911111111', 'route-a', 'scope:attention'))
})

test('prioriza traspasos reales sin avisar por la respuesta del propio equipo', () => {
  const chats = [
    { id: 'a', handoff: { at: '1', reason: 'El contacto pidió atención humana' } },
    { id: 'b', handoff: { at: '2', reason: 'El equipo respondió manualmente' } },
    { id: 'c', handoff: null },
  ]
  assert.deepEqual(humanChats(chats).map((chat) => chat.id), ['a', 'b'])
  assert.deepEqual(unseenHumanRequests(chats, new Set()).map((chat) => chat.id), ['a'])
  assert.deepEqual(unseenHumanRequests(chats, new Set([handoffKey(chats[0])])), [])
  assert.deepEqual(unseenHumanRequests([{ ...chats[0], handoff: { ...chats[0].handoff, at: '3' } }], new Set([handoffKey(chats[0])])).map((chat) => chat.id), ['a'])
})

test('detecta el aviso real de revisión del agente y lo retira tras responder', () => {
  const notice = 'Recibí tu mensaje. Necesito revisar tu consulta antes de responderte bien; quedó pendiente en este chat.'
  const pending = { id: 'lead', timestamp: 123, lastFromMe: true, lastMessage: notice, handoff: null }
  assert.match(attentionOf(pending).reason, /pendiente/)
  assert.deepEqual(unseenHumanRequests([pending], new Set()).map((chat) => chat.id), ['lead'])
  assert.equal(attentionOf({ ...pending, timestamp: 124, lastMessage: 'Respuesta del equipo' }), null)
  assert.equal(attentionOf({ ...pending, lastFromMe: false }), null)
})

test('en modo manual avisa mensajes entrantes sin duplicar respuestas ni grupos', () => {
  const incoming = { id: 'lead', timestamp: 123, unreadCount: 1, lastFromMe: false }
  assert.equal(attentionOf(incoming, 'automatic'), null)
  assert.match(attentionOf(incoming, 'manual').reason, /manual/)
  assert.equal(attentionOf({ ...incoming, lastFromMe: true }, 'manual'), null)
  assert.equal(attentionOf({ ...incoming, isGroup: true }, 'manual'), null)
})
