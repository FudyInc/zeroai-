import test from 'node:test'
import assert from 'node:assert/strict'
import { attentionCaseKey, openAttentionCases, timeAgo, unseenAttentionCases, attentionOf, handoffKey, humanChats, inboxNavigationKey, unseenHumanRequests } from './whatsapp-attention.js'

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

test('los casos de atención avisan una vez y vuelven a avisar si se repiten', () => {
  const a = { clave: 'a', ultima: '2026-10-17T10:00:00', estado: 'abierta' }
  const b = { clave: 'b', ultima: '2026-10-17T10:05:00', estado: 'abierta' }
  const c = { clave: 'c', ultima: '2026-10-17T10:06:00', estado: 'resuelta' }
  assert.deepEqual(openAttentionCases([a, b, c, null]).map((i) => i.clave), ['a', 'b'])
  assert.deepEqual(unseenAttentionCases([a, b, c], new Set()).map((i) => i.clave), ['a', 'b'])
  assert.deepEqual(unseenAttentionCases([a, b], new Set([attentionCaseKey(a)])).map((i) => i.clave), ['b'])
  assert.deepEqual(unseenAttentionCases([{ ...a, ultima: '2026-10-17T11:00:00' }], new Set([attentionCaseKey(a)])).map((i) => i.clave), ['a'])
  assert.deepEqual(unseenAttentionCases(undefined, new Set()), [])
})

test('timeAgo resume la antigüedad en español y tolera fechas inválidas', () => {
  const now = Date.parse('2026-10-17T12:00:00Z')
  assert.equal(timeAgo('2026-10-17T11:59:50Z', now), 'hace un momento')
  assert.equal(timeAgo('2026-10-17T11:45:00Z', now), 'hace 15 min')
  assert.equal(timeAgo('2026-10-17T09:00:00Z', now), 'hace 3 h')
  assert.equal(timeAgo('2026-10-14T12:00:00Z', now), 'hace 3 d')
  assert.equal(timeAgo('', now), '')
  assert.equal(timeAgo('basura', now), '')
})
