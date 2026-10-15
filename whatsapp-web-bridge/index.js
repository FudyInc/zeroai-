'use strict'

const http = require('node:http')
const crypto = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')
const { Client, LocalAuth, MessageMedia, Poll } = require('whatsapp-web.js')
const QRCode = require('qrcode')
const { serializedVoterId } = require('./delivery-poll')
const { isCustomerMessageType } = require('./customer-message')
const { recentInbound } = require('./recovery')
const { CATALOGS, makeCatalogPdf } = require('./catalog-document')
const { actsFor } = require('./account-scope')

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
const recoveredIds = new Set()
let readinessTimer = null
let restartingConnection = false
const sessionDir = path.resolve(process.env.WHATSAPP_WEB_SESSION_DIR || path.join(__dirname, '.session'))
const pendingFile = path.resolve(process.env.WHATSAPP_WEB_PENDING_FILE || path.join(sessionDir, 'inbound-pending.json'))
const clientId = process.env.WHATSAPP_WEB_CLIENT_ID || ''
const catalogImages = new Set([
  'gama-bordes-piscina.jpeg',
  'borde-recto-nariz-50x50.png', 'ladrillo-cruzado-40x40.jpeg',
  'sol-40x40.jpeg', 'sol-rustico-40x40.jpeg',
  'adoquin-40x40.jpeg', 'laja-espanola-40x40.jpeg',
  'gregioriano-40x40.jpeg', 'octagonal-piedra-40x40.jpeg',
  'dormiente-1-16x40.jpeg', 'dormiente-2-16x40.jpeg',
  'deck-50x50.jpeg', 'esquina-piscina-50x50.jpeg',
  'extension-borde-piscina-50x50.jpeg',
])
const catalogDir = path.resolve(__dirname, '../frontend/public/catalog/losetaschile')
const deliveryPollQuestion = '¿Cómo prefieres indicar el lugar de entrega?'
const deliveryPollLocation = '📍 Compartir ubicación'
const deliveryPollAddress = '✍️ Escribir dirección'
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

// Cuánto se tolera fuera de `ready` antes de reiniciar la conexión. Existe por
// el mensaje perdido del 2026-10-13, cuando el puente quedó más de diez minutos
// en `connecting` sin que nadie se enterara. El primer valor, 120 s, resultó
// más corto que una sincronización fría legítima: el 2026-10-14 mató al puente
// cuatro veces seguidas antes de que alcanzara a conectar, y systemd lo
// relanzaba en bucle. El umbral tiene que ser mayor que la sincronización más
// lenta que se considera normal y menor que el bloqueo que se quiere detectar.
const readyTimeoutMs = Math.max(
  60000, Number(process.env.WHATSAPP_WEB_READY_TIMEOUT_MS) || 300000)

function watchReadiness() {
  if (restartingConnection) return
  clearTimeout(readinessTimer)
  readinessTimer = setTimeout(async () => {
    if (!['starting', 'connecting', 'disconnected', 'error', 'auth_failed'].includes(state)) return
    restartingConnection = true
    lastError = `WhatsApp Web quedó en ${state} durante ${Math.round(readyTimeoutMs / 1000)} ` +
      'segundos; reiniciando el puente'
    console.error(lastError)
    const forceExit = setTimeout(() => process.exit(1), 10000)
    try { await client.destroy() } catch (err) { console.error('Bridge cleanup:', err.message) }
    clearTimeout(forceExit)
    process.exit(1)
  }, readyTimeoutMs)
  readinessTimer.unref()
}

async function recoverRecentMessages() {
  if (state !== 'ready') return
  try {
    const cutoff = Math.floor(Date.now() / 1000) - 1800
    const cached = await client.pupPage.evaluate(since =>
      window.require('WAWebCollections').Chat.getModelsArray()
        .filter(chat => /^\d{8,20}@(c\.us|lid)$/.test(chat.id?._serialized || ''))
        .flatMap(chat => {
          const messages = chat.msgs?.getModelsArray?.() || []
          const lastOutgoingTimestamp = messages.reduce((latest, msg) =>
            msg.id?.fromMe ? Math.max(latest, msg.t || 0) : latest, 0)
          return messages
            .filter(msg => !msg.id?.fromMe && (msg.t || 0) >= since)
            .map(msg => ({ id: msg.id?._serialized || '',
              from: msg.from?._serialized || '', fromMe: !!msg.id?.fromMe,
              timestamp: msg.t || 0, type: msg.type || '',
              body: msg.type === 'chat' ? String(msg.body || '') : '',
              lastOutgoingTimestamp }))
        }), cutoff)
    const candidates = recentInbound(cached, Math.floor(Date.now() / 1000))
      .filter(message => isCustomerMessageType(message.type))
    let queued = 0
    for (const candidate of candidates) {
      if (recoveredIds.has(candidate.id)) continue
      try {
        const message = candidate.type === 'chat'
          ? { id: { _serialized: candidate.id }, from: candidate.from,
              fromMe: false, type: 'chat', body: candidate.body,
              getContact: () => client.getContactById(candidate.from) }
          : await client.getMessageById(candidate.id)
        if (!message || message.fromMe || message.from !== candidate.from) continue
        const payload = await normalizeMessage(message)
        if (!payload) continue
        queuePayload(payload)
        recoveredIds.add(candidate.id)
        queued += 1
      } catch (err) {
        console.error('Could not recover cached inbound:', err.message)
      }
    }
    if (queued) console.info(`Recovered ${queued} recent inbound message(s) from WhatsApp Web cache`)
  } catch (err) {
    lastError = `Recuperación entrante: ${err.message}`
    console.error(lastError)
  }
}

client.on('qr', async qr => {
  state = 'scan_qr'
  clearTimeout(readinessTimer)
  account = null
  try { qrDataUrl = await QRCode.toDataURL(qr) } catch (err) { lastError = err.message }
})
client.on('authenticated', () => { state = 'connecting'; qrDataUrl = null; watchReadiness() })
client.on('ready', () => {
  state = 'ready'
  clearTimeout(readinessTimer)
  qrDataUrl = null
  lastError = null
  account = client.info?.wid?.user || null
  setTimeout(() => { void recoverRecentMessages() }, 5000).unref()
  setTimeout(() => { void recoverRecentMessages() }, 30000).unref()
})
client.on('auth_failure', message => { state = 'auth_failed'; lastError = String(message); watchReadiness() })
client.on('disconnected', reason => { state = 'disconnected'; account = null; lastError = String(reason); watchReadiness() })

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
  if (!isCustomerMessageType(msg.type)) return null
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
    let body = msg.type === 'chat' ? msg.body : `[${msg.type || 'mensaje'}]`
    if (msg.type === 'location') {
      const lat = msg.location?.latitude
      const lon = msg.location?.longitude
      if (typeof lat === 'number' && typeof lon === 'number' &&
          Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180) {
        body = `[location] https://www.google.com/maps?q=${lat.toFixed(6)},${lon.toFixed(6)}`
      }
    }
    let contact = null
    try { contact = await msg.getContact() } catch (_) { /* Nombre opcional. */ }
    const profileName = String(contact?.pushname || msg?._data?.notifyName || '')
      .replace(/\s+/g, ' ').trim().slice(0, 80)
    const messageId = msg.id?._serialized || msg.id
    const payload = { id: clientId ? `${clientId}:${messageId}` : messageId,
      from, chat_id: senderId, text: body,
      to_phone_id: account || client.info?.wid?.user || '' }
    if (/\p{L}/u.test(profileName)) payload.profile_name = profileName
    return payload
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

function queuePayload(payload) {
  if (!payload || !payload.id || pending.has(payload.id)) return
  pending.set(payload.id, payload)
  savePending()
  void drainPending()
}

async function queueMessage(msg) {
  queuePayload(await normalizeMessage(msg))
}

client.on('message', msg => {
  messageEvents += 1
  const senderId = String(msg.from || '')
  recentEvents.unshift({ at: new Date().toISOString(), sender_kind: senderId.split('@')[1] || '', type: msg.type || '', from_me: !!msg.fromMe })
  recentEvents.length = Math.min(recentEvents.length, 10)
  void queueMessage(msg).catch(err => { lastError = `Cola entrante: ${err.message}`; console.error(lastError) })
})

client.on('vote_update', vote => {
  void (async () => {
    if (!actsFor(clientId, 'losetaschile')) return
    const poll = vote.parentMessage
    const chatId = poll?.to?._serialized || String(poll?.to || '')
    const voterId = serializedVoterId(vote.voter)
    const selected = vote.selectedOptions || []
    const choice = selected.length === 1 ? selected[0]?.name : null
    const pollId = messageId(poll)
    if (!poll?.fromMe || poll.type !== 'poll_creation' ||
        poll.pollName !== deliveryPollQuestion || !pollId ||
        !/^\d{8,20}@(c\.us|lid)$/.test(chatId) ||
        !/^\d{8,20}@(c\.us|lid)$/.test(voterId) ||
        ![deliveryPollLocation, deliveryPollAddress].includes(choice)) return
    const options = (poll.pollOptions || []).map(option => option.name)
    if (options.length !== 2 || !options.includes(deliveryPollLocation) ||
        !options.includes(deliveryPollAddress)) return
    const syntheticId = 'delivery-poll:' + crypto.createHash('sha256')
      .update(JSON.stringify([pollId, voterId, choice])).digest('hex')
    const payload = await normalizeMessage({
      id: { _serialized: syntheticId }, from: voterId, fromMe: false,
      type: 'chat', body: choice,
      getContact: () => client.getContactById(voterId),
    })
    if (!payload) return
    if (chatId.endsWith('@c.us') && payload.from !== chatId.split('@')[0]) return
    if (chatId.endsWith('@lid') && voterId !== chatId) {
      const matches = await client.getContactLidAndPhone(chatId)
      const chatPhone = matches?.[0]?.pn?.split('@')[0]
      if (!chatPhone || payload.from !== chatPhone) return
    }
    payload.chat_id = chatId
    queuePayload(payload)
  })().catch(err => { lastError = `Voto de encuesta: ${err.message}`; console.error(lastError) })
})

function respond(res, status, body) {
  const data = Buffer.from(JSON.stringify(body))
  res.writeHead(status, { 'Content-Type': 'application/json', 'Content-Length': data.length, 'Cache-Control': 'no-store' })
  res.end(data)
}

function summary(chat) {
  const last = chat.lastMessage
  return {
    id: chat.id?._serialized || '',
    name: chat.name || chat.id?.user || 'Sin nombre',
    isGroup: !!chat.isGroup,
    unreadCount: chat.unreadCount || 0,
    timestamp: last?.timestamp || chat.timestamp || null,
    lastMessage: last ? (last.type === 'chat' ? last.body : `[${last.type || 'archivo'}]`) : '',
    lastFromMe: !!last?.fromMe,
  }
}

function messageData(message) {
  return {
    id: message.id?._serialized || '',
    body: message.type === 'chat' ? message.body : `[${message.type || 'archivo'}]`,
    type: message.type,
    fromMe: !!message.fromMe,
    timestamp: message.timestamp || null,
    author: message.author || null,
  }
}

async function selectedChat(id) {
  if (!/^[^/]{1,100}@(c\.us|g\.us|lid)$/.test(id)) return null
  return await client.pupPage.evaluate(chatId => {
    const chat = window.require('WAWebCollections').Chat.getModelsArray()
      .find(item => item.id?._serialized === chatId)
    if (!chat) return null
    return {
      id: chatId,
      name: chat.formattedTitle || chat.name || chat.id?.user || 'Sin nombre',
      isGroup: chatId.endsWith('@g.us'),
      unreadCount: chat.unreadCount || 0,
      timestamp: chat.t || null,
    }
  }, id)
}

function messageId(message) {
  const id = message?.id?._serialized || message?.id?.toString?.()
  return typeof id === 'string' && id !== '[object Object]' ? id : null
}

async function sendAndConfirm(chatId, content, options, matchesCreated, expectedType, expectedBody) {
  let confirmCreated
  const created = new Promise(resolve => { confirmCreated = resolve })
  const onCreated = message => {
    const destination = message.to?._serialized || String(message.to || '')
    const id = messageId(message)
    if (message.fromMe && destination === chatId && id && matchesCreated(message)) {
      confirmCreated({ id, ack: message.ack ?? null })
    }
  }
  client.on('message_create', onCreated)
  try {
    const startedAt = Math.floor(Date.now() / 1000)
    const sent = await client.sendMessage(chatId, content, {
      sendSeen: false, waitUntilMsgSent: true, ...options,
    })
    const sentId = messageId(sent)
    let confirmed = sentId ? { id: sentId, ack: sent.ack ?? null } : await Promise.race([
      created, new Promise(resolve => setTimeout(() => resolve(null), 3000)),
    ])
    if (!confirmed?.id) {
      confirmed = await client.pupPage.evaluate((id, kind, body, since) => {
        const chat = window.require('WAWebCollections').Chat.getModelsArray()
          .find(item => item.id?._serialized === id)
          const message = (chat?.msgs?.getModelsArray?.() || [])
            .find(item => item.id?.fromMe && item.type === kind &&
              (kind === 'image' || kind === 'document' ? item.caption || item.body :
                kind === 'poll_creation' ? (item.pollName || item.body) : item.body) === body &&
              (item.t || 0) >= since)
        const rawId = message?.id?._serialized || message?.id?.toString?.()
        return rawId && rawId !== '[object Object]'
          ? { id: rawId, ack: message.ack ?? null } : null
      }, chatId, expectedType, expectedBody, startedAt)
    }
    if (!confirmed?.id) return null // Outcome unknown. Never retry automatically.
    return confirmed
  } finally { client.off('message_create', onCreated) }
}

async function prepareMediaSend() {
  // whatsapp-web.js spreads MediaData into the outgoing Msg. Its private
  // __x_id can replace the Msg ID and make image sends fail before creation.
  // Preserve that field for MediaData, but keep it out of the object spread.
  // See wwebjs/whatsapp-web.js#201922. Reapply after a Web page reload.
  await client.pupPage.evaluate(() => {
    const api = window.WWebJS
    if (api?.__zeroMediaIdPatch) return
    if (typeof api?.processMediaData !== 'function') {
      throw new Error('WhatsApp Web media processor unavailable')
    }
    const original = api.processMediaData
    api.processMediaData = async function (...args) {
      const mediaData = await original.apply(this, args)
      const id = Object.getOwnPropertyDescriptor(mediaData, '__x_id')
      if (id?.enumerable) {
        if (!id.configurable) throw new Error('WhatsApp Web media ID cannot be isolated')
        Object.defineProperty(mediaData, '__x_id', { ...id, enumerable: false })
      }
      return mediaData
    }
    api.__zeroMediaIdPatch = true
  })
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
  if (url.pathname === '/chats' || /^\/chats\/[^/]+\/messages$/.test(url.pathname)) {
    if (state !== 'ready') return respond(res, 503, { error: 'WhatsApp Web is not ready' })
    try {
      if (req.method === 'GET' && url.pathname === '/chats') {
        // getChats() serializes every chat, including groups. One stale group
        // can reject the whole list on current WhatsApp Web builds.
        const chats = await client.pupPage.evaluate(() =>
          window.require('WAWebCollections').Chat.getModelsArray()
            .map(chat => {
              const messages = chat.msgs?.getModelsArray?.() || []
              const last = messages.reduce((newest, msg) => !newest || (msg.t || 0) > (newest.t || 0) ? msg : newest, null)
              const id = chat.id?._serialized || ''
              return {
                id,
                name: chat.formattedTitle || chat.name || chat.id?.user || 'Sin nombre',
                isGroup: id.endsWith('@g.us'),
                unreadCount: chat.unreadCount || 0,
                timestamp: last?.t || chat.t || null,
                lastMessage: last ? (last.type === 'chat' ? String(last.body || '') : `[${last.type || 'archivo'}]`) : '',
                lastFromMe: !!last?.id?.fromMe,
              }
            })
        )
        return respond(res, 200, { chats: chats.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0)).slice(0, 200) })
      }
      const match = url.pathname.match(/^\/chats\/([^/]+)\/messages$/)
      if (!match) return respond(res, 405, { error: 'method not allowed' })
      const chat = await selectedChat(decodeURIComponent(match[1]))
      if (!chat) return respond(res, 404, { error: 'Chat no encontrado' })
      if (req.method === 'GET') {
        const limit = Math.min(100, Math.max(1, Number(url.searchParams.get('limit')) || 50))
        const messages = await client.pupPage.evaluate((chatId, max) => {
          const model = window.require('WAWebCollections').Chat.getModelsArray()
            .find(item => item.id?._serialized === chatId)
          const cached = model?.msgs?.getModelsArray?.() || []
          return cached.sort((a, b) => (b.t || 0) - (a.t || 0)).slice(0, max).map(msg => ({
            id: msg.id?._serialized || '',
            body: msg.type === 'chat' ? String(msg.body || '') : `[${msg.type || 'archivo'}]`,
            type: msg.type,
            fromMe: !!msg.id?.fromMe,
            ack: msg.ack ?? null,
            timestamp: msg.t || null,
            author: msg.author?._serialized || null,
          }))
        }, chat.id, limit)
        return respond(res, 200, { chat, messages: messages.sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0)) })
      }
      if (req.method === 'POST') {
        let raw = ''
        for await (const chunk of req) {
          raw += chunk
          if (raw.length > 20000) return respond(res, 413, { error: 'Mensaje demasiado largo' })
        }
        const text = String(JSON.parse(raw).text || '').trim()
        if (!text || text.length > 4096) return respond(res, 400, { error: 'Mensaje inválido' })
        const sent = await client.sendMessage(chat.id, text)
        return respond(res, 200, { message: messageData(sent) })
      }
      return respond(res, 405, { error: 'method not allowed' })
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
  if (req.method === 'POST' && (req.url === '/send-group' || req.url === '/send-catalog-image' ||
                                req.url === '/send-catalog-document' ||
                                req.url === '/send-delivery-poll')) {
    if (state !== 'ready') return respond(res, 503, { error: 'WhatsApp Web is not ready' })
    let raw = ''
    for await (const chunk of req) {
      raw += chunk
      if (raw.length > 20000) return respond(res, 413, { error: 'too large' })
    }
    try {
      const body = JSON.parse(raw)
      if (req.url === '/send-group') {
        const groupId = String(body.group_id || '')
        const text = String(body.text || '').trim()
        if (!/^[0-9-]{8,40}@g\.us$/.test(groupId) || !text || text.length > 4096) {
          return respond(res, 400, { error: 'invalid group or text' })
        }
        const group = await selectedChat(groupId)
        if (!group?.isGroup) return respond(res, 404, { error: 'group not found on this account' })
        const result = await sendAndConfirm(groupId, text, {}, message =>
          message.type === 'chat' && message.body === text, 'chat', text)
        return result ? respond(res, 200, result)
          : respond(res, 502, { error: 'Group send outcome uncertain; review chat before retry' })
      }
      if (req.url === '/send-delivery-poll') {
        if (!actsFor(clientId, 'losetaschile')) return respond(res, 403, { error: 'poll not allowed for this account' })
        const number = String(body.to || '').replace(/\D/g, '')
        const chatId = String(body.chat_id || `${number}@c.us`)
        if (!/^\d{8,15}$/.test(number) || !/^\d{8,20}@(c\.us|lid)$/.test(chatId) ||
            (chatId.endsWith('@c.us') && chatId.split('@')[0] !== number)) {
          return respond(res, 400, { error: 'invalid poll recipient' })
        }
        const poll = new Poll(deliveryPollQuestion,
          [deliveryPollLocation, deliveryPollAddress], { allowMultipleAnswers: false })
        const result = await sendAndConfirm(chatId, poll, {}, message =>
          message.type === 'poll_creation' &&
          (message.pollName === deliveryPollQuestion || message.body === deliveryPollQuestion),
        'poll_creation', deliveryPollQuestion)
        return result ? respond(res, 200, result)
          : respond(res, 502, { error: 'Poll send outcome uncertain; review chat before retry' })
      }
      if (req.url === '/send-catalog-document') {
        if (!actsFor(clientId, 'losetaschile')) return respond(res, 403, { error: 'catalog document not allowed for this account' })
        const number = String(body.to || '').replace(/\D/g, '')
        const chatId = String(body.chat_id || `${number}@c.us`)
        const category = String(body.category || '')
        const prices = body.prices
        if (!/^\d{8,15}$/.test(number) || !/^\d{8,20}@(c\.us|lid)$/.test(chatId) ||
            (chatId.endsWith('@c.us') && chatId.split('@')[0] !== number) ||
            !CATALOGS[category] || !prices || typeof prices !== 'object' || Array.isArray(prices)) {
          return respond(res, 400, { error: 'invalid catalog document request' })
        }
        const pdf = await makeCatalogPdf(client.pupBrowser, category, prices, catalogDir)
        const caption = CATALOGS[category].title
        const filename = category === 'bordes' ? 'catalogo-bordes-de-piscina.pdf' : 'catalogo-pastelones.pdf'
        const media = new MessageMedia('application/pdf', pdf.toString('base64'), filename)
        await prepareMediaSend()
        const result = await sendAndConfirm(chatId, media,
          { caption, sendMediaAsDocument: true }, message =>
            message.type === 'document' && (message.caption === caption ||
              message._data?.caption === caption || message.filename === filename),
          'document', caption)
        return result ? respond(res, 200, result)
          : respond(res, 502, { error: 'Catalog document outcome uncertain; review chat before retry' })
      }
      const number = String(body.to || '').replace(/\D/g, '')
      const chatId = String(body.chat_id || `${number}@c.us`)
      const image = String(body.image || '')
      const caption = String(body.caption || '').trim()
      if (!/^\d{8,15}$/.test(number) || !/^\d{8,20}@(c\.us|lid)$/.test(chatId) ||
          (chatId.endsWith('@c.us') && chatId.split('@')[0] !== number) ||
          !catalogImages.has(image) || !caption || caption.length > 1024) {
        return respond(res, 400, { error: 'invalid recipient, catalog image or caption' })
      }
      const imagePath = path.resolve(catalogDir, image)
      const media = MessageMedia.fromFilePath(imagePath)
      await prepareMediaSend()
      const result = await sendAndConfirm(chatId, media, { caption }, message =>
        message.type === 'image' && (message.caption === caption ||
          message._data?.caption === caption), 'image', caption)
      return result ? respond(res, 200, result)
        : respond(res, 502, { error: 'Image send outcome uncertain; review chat before retry' })
    } catch (err) {
      lastError = err.message
      return respond(res, 502, { error: `WhatsApp Web send failed: ${err.message}` })
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
    if (!/^\d{8,15}$/.test(number) || !text || text.length > 4096) {
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
        linkPreview: body.link_preview !== false,
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
    return respond(res, 502, { error: `WhatsApp Web send failed: ${err.message}` })
  }
})

server.listen(port, host, () => console.log(`WhatsApp bridge listening on ${host}:${port}`))
watchReadiness()
client.initialize().catch(err => { state = 'error'; lastError = err.message; console.error(err); watchReadiness() })
if (pending.size) void drainPending()
setInterval(() => { if (pending.size) void drainPending() }, 10000).unref()
