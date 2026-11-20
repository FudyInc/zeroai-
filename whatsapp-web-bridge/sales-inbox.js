'use strict'

const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const crypto = require('node:crypto')
const { stableMessageId } = require('./message-id')

function attachSalesInbox(client, sessionDir, {
  inbox = process.env.POOLEDGE_EXCEL_INBOX || path.join(os.homedir(), '.local/state/pooledge-excel/inbox'),
  onError = error => console.error('Captura de Vendidos Diego:', error.code || error.name),
} = {}) {
  const status = { enabled: false, lastCapture: null, error: null }
  let group
  try {
    group = fs.readFileSync(path.join(sessionDir, 'vendidos-diego-group'), 'utf8').trim()
    if (!/^\d[\d-]{7,39}@g\.us$/.test(group)) throw new Error('InvalidGroup')
    fs.mkdirSync(inbox, { recursive: true, mode: 0o700 })
  } catch (error) {
    if (error.code !== 'ENOENT') {
      status.error = error.code || 'InvalidGroup'
      onError(error)
    }
    return status
  }

  const failed = new Map()
  function persist(event) {
    const key = crypto.createHash('sha256').update(event.id).digest('hex')
    const dest = path.join(inbox, key + '.json')
    const tmp = path.join(inbox, '.' + crypto.randomUUID() + '.tmp')
    try {
      const fd = fs.openSync(tmp, 'wx', 0o600)
      try {
        fs.writeFileSync(fd, JSON.stringify(event))
        fs.fsyncSync(fd)
      } finally { fs.closeSync(fd) }
      fs.renameSync(tmp, dest)
      const dir = fs.openSync(inbox, 'r')
      try { fs.fsyncSync(dir) } finally { fs.closeSync(dir) }
      failed.delete(event.id)
      status.lastCapture = new Date().toISOString()
      if (!failed.size) status.error = null
    } catch (error) {
      failed.set(event.id, event)
      status.error = error.code || 'WriteError'
      onError(error)
    } finally {
      try { fs.unlinkSync(tmp) } catch (error) { if (error.code !== 'ENOENT') onError(error) }
    }
  }
  setInterval(() => {
    for (const event of failed.values()) persist(event)
  }, 30000).unref()
  client.on('message_create', msg => {
    if (msg.type !== 'chat' || typeof msg.body !== 'string' || !/\bPE-\d{6}-\d+\b/.test(msg.body)) return
    const id = stableMessageId(msg.id)
    const remote = msg.fromMe ? msg.to : msg.from
    const chatId = id?.split('_')[1] || remote?._serialized || remote
    if (chatId !== group) return
    if (!id || !Number.isSafeInteger(msg.timestamp) || msg.timestamp <= 0) {
      status.error = 'InvalidMessage'
      onError(new Error('InvalidMessage'))
      return
    }
    persist({ id, body: msg.body, timestamp: msg.timestamp, type: 'chat', chat_id: group })
  })
  status.enabled = true
  return status
}

module.exports = { attachSalesInbox }
