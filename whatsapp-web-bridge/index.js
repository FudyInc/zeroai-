'use strict'

const http = require('node:http')
const crypto = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')
const { Client, LocalAuth } = require('whatsapp-web.js')
const QRCode = require('qrcode')

const host = '127.0.0.1'
const port = Number(process.env.WHATSAPP_WEB_BRIDGE_PORT || 8810)
const secret = process.env.WHATSAPP_WEB_BRIDGE_TOKEN
const backend = process.env.WHATSAPP_WEB_BACKEND_URL || 'http://127.0.0.1:8800/api/webhooks/whatsapp-web'
if (!secret || secret.length < 32) {
  console.error('WHATSAPP_WEB_BRIDGE_TOKEN must be set to at least 32 characters')
  process.exit(1)
}

let state = 'starting'
let qrDataUrl = null
let lastError = null
let account = null
let messageEvents = 0
let forwardedMessages = 0
const recentEvents = []
const sessionDir = path.resolve(process.env.WHATSAPP_WEB_SESSION_DIR || path.join(__dirname, '.session'))
const pendingFile = path.resolve(process.env.WHATSAPP_WEB_PENDING_FILE || path.join(sessionDir, 'inbound-pending.json'))
const clientId = process.env.WHATSAPP_WEB_CLIENT_ID || ''
function loadPending() {
  try { return new Map(JSON.parse(fs.readFileSync(pendingFile, 'utf8')).map(item => [item.id, item])) }
  catch (err) {
    if (err.code === 'ENOENT') return new Map()
    throw err // A corrupt queue must be repaired, never silently replaced.
  }
}
const pending = loadPending()
let draining = false
function savePending() {
  fs.mkdirSync(path.dirname(pendingFile), { recursive: true, mode: 0o700 })
  const tmp = pendingFile + '.tmp'
  fs.writeFileSync(tmp, JSON.stringify([...pending.values()]), { mode: 0o600 })
  fs.renameSync(tmp, pendingFile)
}
const client = new Client({
  authStrategy: new LocalAuth({ dataPath: sessionDir }),
  puppeteer: {
    executablePath: process.env.WHATSAPP_WEB_CHROME || undefined,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  },
})

client.on('qr', async qr => {
  state = 'scan_qr'
  account = null
  try { qrDataUrl = await QRCode.toDataURL(qr) } catch (err) { lastError = err.message }
})
client.on('authenticated', () => { state = 'connecting'; qrDataUrl = null })
client.on('ready', () => {
  state = 'ready'
  qrDataUrl = null
  lastError = null
  account = client.info?.wid?.user || null
  if (account && [...pending.values()].some(message => !message.to_phone_id)) {
    for (const message of pending.values()) {
      if (!message.to_phone_id) message.to_phone_id = account
    }
    savePending()
  }
  if (pending.size) void drainPending()
})
client.on('auth_failure', message => { state = 'auth_failed'; lastError = String(message) })
client.on('disconnected', reason => { state = 'disconnected'; account = null; lastError = String(reason) })

async function forward(message) {
  const raw = JSON.stringify(message)
  const signature = crypto.createHmac('sha256', secret).update(raw).digest('hex')
  for (let attempt = 0; attempt < 4; attempt++) {
    try {
      const response = await fetch(backend, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Zero-Signature': `sha256=${signature}` },
        body: raw,
        signal: AbortSignal.timeout(10000),
      })
      if (response.ok) return true
      lastError = `Backend respondió HTTP ${response.status}`
    } catch (err) { lastError = `Backend: ${err.message}` }
    await new Promise(resolve => setTimeout(resolve, 1000 * (attempt + 1)))
  }
  console.error('Inbound not delivered to ZeroAI:', message.id, lastError)
  return false
}

async function normalizeMessage(msg) {
  const senderId = String(msg.from || '')
  if (msg.fromMe || (!senderId.endsWith('@c.us') && !senderId.endsWith('@lid'))) return null
  try {
    let from = senderId.endsWith('@c.us') ? senderId.split('@')[0] : null
    if (!from) {
      const matches = await client.getContactLidAndPhone(senderId)
      from = matches?.[0]?.pn?.split('@')[0] || null
    }
    if (!from) {
      const contact = await msg.getContact()
      from = contact?.number || null
    }
    if (!/^\d{8,15}$/.test(from || '')) {
      lastError = 'No se pudo resolver el teléfono del remitente'
      return null
    }
    const body = msg.type === 'chat' ? msg.body : `[${msg.type || 'mensaje'}]`
    const messageId = msg.id?._serialized || msg.id
    return { id: clientId ? `${clientId}:${messageId}` : messageId,
      from, chat_id: senderId, text: body,
      to_phone_id: account || client.info?.wid?.user || '' }
  } catch (err) {
    lastError = `Mensaje entrante: ${err.message}`
    console.error(lastError)
  }
  return null
}

async function forwardMessage(msg) {
  const payload = await normalizeMessage(msg)
  if (!payload) return false
  const delivered = await forward(payload)
  if (delivered) forwardedMessages += 1
  return delivered
}

async function drainPending() {
  if (draining) return
  draining = true
  try {
    while (pending.size) {
      const message = pending.values().next().value
      if (await forward(message)) {
        pending.delete(message.id)
        savePending()
        forwardedMessages += 1
      } else {
        await new Promise(resolve => setTimeout(resolve, 5000))
      }
    }
  } catch (err) {
    lastError = `Cola entrante: ${err.message}`
    console.error(lastError)
  } finally { draining = false }
}

async function queueMessage(msg) {
  const payload = await normalizeMessage(msg)
  if (!payload || !payload.id || pending.has(payload.id)) return
  pending.set(payload.id, payload)
  savePending()
  void drainPending()
}

client.on('message', msg => {
  messageEvents += 1
  const senderId = String(msg.from || '')
  recentEvents.unshift({ at: new Date().toISOString(), sender_kind: senderId.split('@')[1] || '', type: msg.type || '', from_me: !!msg.fromMe })
  recentEvents.length = Math.min(recentEvents.length, 10)
  void queueMessage(msg).catch(err => { lastError = `Cola entrante: ${err.message}`; console.error(lastError) })
})

function respond(res, status, body) {
  const data = Buffer.from(JSON.stringify(body))
  res.writeHead(status, { 'Content-Type': 'application/json', 'Content-Length': data.length, 'Cache-Control': 'no-store' })
  res.end(data)
}

function messageId(message) {
  const id = message?.id?._serialized || message?.id?.toString?.()
  return typeof id === 'string' && id !== '[object Object]' ? id : null
}

const server = http.createServer(async (req, res) => {
  if (req.headers.authorization !== `Bearer ${secret}`) return respond(res, 401, { error: 'unauthorized' })
  const url = new URL(req.url, 'http://127.0.0.1')
  if (req.method === 'GET' && req.url === '/status') {
    return respond(res, 200, { state, qr: qrDataUrl, account, error: lastError, pendingInbound: pending.size })
  }
  if (req.method === 'GET' && req.url === '/diagnostics') {
    try {
      const recentChats = state === 'ready' ? await client.pupPage.evaluate(() => {
        const chats = window.require('WAWebCollections').Chat.getModelsArray()
        return chats.map(chat => {
          const messages = chat.msgs?.getModelsArray?.() || []
          const last = messages.sort((a, b) => (b.t || 0) - (a.t || 0))[0]
          return {
            kind: String(chat.id?._serialized || '').split('@')[1] || '',
            timestamp: chat.t || null,
            cached_messages: messages.length,
            last_message_at: last?.t || null,
            last_message_from_me: last?.id?.fromMe ?? null,
            last_message_kind: String(last?.from?._serialized || '').split('@')[1] || '',
            last_message_type: last?.type || null,
          }
        }).sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0)).slice(0, 10)
      }) : []
      return respond(res, 200, { state, messageEvents, forwardedMessages, pendingInbound: pending.size, recentEvents, recentChats })
    } catch (err) { return respond(res, 500, { error: err.message, messageEvents, forwardedMessages, recentEvents }) }
  }
  if (req.method === 'GET' && (url.pathname === '/chats' || /^\/chats\/[^/]+\/messages$/.test(url.pathname))) {
    if (state !== 'ready') return respond(res, 503, { error: 'WhatsApp Web is not ready' })
    try {
      if (url.pathname === '/chats') {
        const chats = await client.pupPage.evaluate(() =>
          window.require('WAWebCollections').Chat.getModelsArray().map(chat => {
            const messages = chat.msgs?.getModelsArray?.() || []
            const last = messages.reduce((newest, msg) =>
              !newest || (msg.t || 0) > (newest.t || 0) ? msg : newest, null)
            const id = chat.id?._serialized || ''
            return {
              id, name: chat.formattedTitle || chat.name || chat.id?.user || 'Sin nombre',
              isGroup: id.endsWith('@g.us'), unreadCount: chat.unreadCount || 0,
              timestamp: last?.t || chat.t || null,
              lastMessage: last ? (last.type === 'chat' ? String(last.body || '') : `[${last.type || 'archivo'}]`) : '',
              lastFromMe: !!last?.id?.fromMe,
            }
          })
        )
        return respond(res, 200, { chats: chats.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0)).slice(0, 200) })
      }
      const chatId = decodeURIComponent(url.pathname.match(/^\/chats\/([^/]+)\/messages$/)[1])
      if (!/^[^/]{1,100}@(c\.us|g\.us|lid)$/.test(chatId)) return respond(res, 400, { error: 'invalid chat id' })
      const limit = Math.min(100, Math.max(1, Number(url.searchParams.get('limit')) || 50))
      const result = await client.pupPage.evaluate((id, max) => {
        const chat = window.require('WAWebCollections').Chat.getModelsArray()
          .find(item => item.id?._serialized === id)
        if (!chat) return null
        const cached = chat.msgs?.getModelsArray?.() || []
        return {
          chat: { id, name: chat.formattedTitle || chat.name || chat.id?.user || 'Sin nombre',
            isGroup: id.endsWith('@g.us'), unreadCount: chat.unreadCount || 0,
            timestamp: chat.t || null },
          messages: cached.sort((a, b) => (b.t || 0) - (a.t || 0)).slice(0, max)
            .map(msg => ({ id: msg.id?._serialized || '',
              body: msg.type === 'chat' ? String(msg.body || '') : `[${msg.type || 'archivo'}]`,
              type: msg.type, fromMe: !!msg.id?.fromMe, timestamp: msg.t || null,
              author: msg.author?._serialized || null }))
            .sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0)),
        }
      }, chatId, limit)
      return result ? respond(res, 200, result) : respond(res, 404, { error: 'Chat no encontrado' })
    } catch (err) {
      console.error('WhatsApp Web inbox:', err)
      return respond(res, 502, { error: 'No se pudo consultar WhatsApp Web' })
    }
  }
  if (req.method === 'POST' && req.url === '/replay-latest') {
    if (state !== 'ready') return respond(res, 503, { error: 'WhatsApp Web is not ready' })
    try {
      const message = await client.pupPage.evaluate(() => {
        const chats = window.require('WAWebCollections').Chat.getModelsArray()
        const messages = chats.flatMap(chat => chat.msgs?.getModelsArray?.() || [])
        const latest = messages.filter(msg => !msg.id?.fromMe && msg.type === 'chat')
          .sort((a, b) => (b.t || 0) - (a.t || 0))[0]
        if (!latest) return null
        return { id: latest.id?._serialized || latest.id?.id || null, from: latest.from?._serialized,
          fromMe: latest.id?.fromMe, type: latest.type, body: latest.body, timestamp: latest.t }
      })
      if (message && !message.id && message.from && message.body && message.timestamp) {
        message.id = 'replay-' + crypto.createHash('sha256')
          .update(JSON.stringify([message.from, message.timestamp, message.body])).digest('hex')
      }
      if (!message || !message.id || !message.from || (Date.now() / 1000 - message.timestamp) > 1800) {
        return respond(res, 409, { error: 'No recent inbound message to replay',
          found: !!message, id_present: !!message?.id, from_present: !!message?.from,
          body_chars: message?.body?.length || 0,
          age_seconds: message?.timestamp ? Math.round(Date.now() / 1000 - message.timestamp) : null })
      }
      const delivered = await forwardMessage(message)
      return respond(res, delivered ? 200 : 502, { delivered, error: delivered ? null : lastError })
    } catch (err) {
      lastError = `Replay: ${err.message}`
      return respond(res, 502, { error: lastError })
    }
  }
  if (req.method !== 'POST' || req.url !== '/send') return respond(res, 404, { error: 'not found' })
  if (state !== 'ready') return respond(res, 503, { error: 'WhatsApp Web is not ready' })
  let raw = ''
  for await (const chunk of req) {
    raw += chunk
    if (raw.length > 20000) return respond(res, 413, { error: 'too large' })
  }
  try {
    const body = JSON.parse(raw)
    const number = String(body.to || '').replace(/\D/g, '')
    const text = String(body.text || '').trim()
    const chatId = body.chat_id || `${number}@c.us`
    const validRecipient = /^\d{8,15}$/.test(number) ||
      (chatId === `${number}@lid` && /^\d{8,20}$/.test(number))
    if (!validRecipient || !text || text.length > 4096) {
      return respond(res, 400, { error: 'invalid recipient or text' })
    }
    if (!/^\d{8,20}@(c\.us|lid)$/.test(chatId)) {
      return respond(res, 400, { error: 'invalid chat id' })
    }
    // This library can resolve sendMessage() with undefined after the message was
    // created in WhatsApp. Listen before sending so that result is not lost.
    let confirmCreated
    const created = new Promise(resolve => { confirmCreated = resolve })
    const onCreated = message => {
      const destination = message.to?._serialized || String(message.to || '')
      const id = messageId(message)
      if (message.fromMe && message.type === 'chat' && message.body === text &&
          destination === chatId && id) {
        confirmCreated({ id, ack: message.ack ?? null })
      }
    }
    client.on('message_create', onCreated)
    try {
      const startedAt = Math.floor(Date.now() / 1000)
      const sent = await client.sendMessage(chatId, text, {
        sendSeen: false, waitUntilMsgSent: true,
      })
      const sentId = messageId(sent)
      let confirmed = sentId ? { id: sentId, ack: sent.ack ?? null } : await Promise.race([
        created, new Promise(resolve => setTimeout(() => resolve(null), 3000)),
      ])
      if (!confirmed?.id) {
        confirmed = await client.pupPage.evaluate((id, body, since) => {
          const chat = window.require('WAWebCollections').Chat.getModelsArray()
            .find(item => item.id?._serialized === id)
          const message = (chat?.msgs?.getModelsArray?.() || [])
            .find(item => item.id?.fromMe && item.type === 'chat' &&
              item.body === body && (item.t || 0) >= since)
          const rawId = message?.id?._serialized || message?.id?.toString?.()
          return rawId && rawId !== '[object Object]'
            ? { id: rawId, ack: message.ack ?? null } : null
        }, chatId, text, startedAt)
      }
      if (!confirmed?.id) return respond(res, 502, { error: 'WhatsApp Web no confirmó el envío' })
      return respond(res, 200, { id: confirmed.id, ack: confirmed.ack ?? null })
    } finally { client.off('message_create', onCreated) }
  } catch (err) {
    lastError = err.message
    return respond(res, 502, { error: 'WhatsApp Web send failed' })
  }
})

server.listen(port, host, () => console.log(`WhatsApp bridge listening on ${host}:${port}`))
client.initialize().catch(err => { state = 'error'; lastError = err.message; console.error(err) })
if (pending.size) void drainPending()
setInterval(() => { if (pending.size) void drainPending() }, 10000).unref()
