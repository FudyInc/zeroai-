'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { EventEmitter } = require('node:events')
const { attachSalesInbox } = require('./sales-inbox')

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pooledge-capture-'))
const inbox = path.join(dir, 'inbox')
const group = '123456789@g.us'
const settings = path.join(dir, 'vendidos-diego-group')
const msg = {
  type: 'chat', timestamp: 1700000100,
  body: 'Presupuesto PE-201126-1001',
  id: { fromMe: false, remote: group, id: 'ABC123' },
}
const client = new EventEmitter()
try {
  assert.equal(attachSalesInbox(client, dir, { inbox }).enabled, false)
  fs.writeFileSync(settings, 'invalid')
  assert.equal(attachSalesInbox(client, dir, { inbox, onError() {} }).enabled, false)
  assert.equal(client.listenerCount('message_create'), 0)

  fs.writeFileSync(settings, group)
  const state = attachSalesInbox(client, dir, { inbox })
  assert.equal(state.enabled, true)
  client.emit('message_create', { ...msg, body: 'Gracias!' })
  client.emit('message_create', { ...msg, type: 'image' })
  client.emit('message_create', { ...msg, id: { ...msg.id, remote: '999999999@g.us' } })
  assert.deepEqual(fs.readdirSync(inbox), [])
  client.emit('message_create', msg)
  client.emit('message_create', msg)
  client.emit('message_create', { ...msg, fromMe: true, to: group, id: 'true_' + group + '_ABC456' })
  const files = fs.readdirSync(inbox)
  assert.equal(files.length, 2)
  const events = files.map(file => {
    assert.match(file, /^[0-9a-f]{64}\.json$/)
    const pathname = path.join(inbox, file)
    assert.equal(fs.statSync(pathname).mode & 0o777, 0o600)
    return JSON.parse(fs.readFileSync(pathname, 'utf8'))
  })
  assert.deepEqual(events.map(e => e.id).sort(), ['false_' + group + '_ABC123', 'true_' + group + '_ABC456'])
  for (const event of events) {
    assert.deepEqual(event, { id: event.id, body: msg.body, timestamp: msg.timestamp, type: 'chat', chat_id: group })
  }
  assert.ok(state.lastCapture)
  assert.equal(state.error, null)
} finally {
  fs.rmSync(dir, { recursive: true, force: true })
}
console.log('Captura de presupuestos OK')
