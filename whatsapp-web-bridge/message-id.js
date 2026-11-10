'use strict'

// whatsapp-web.js serializa msg.id desde la página. En algunas versiones de
// WhatsApp Web la llave `_serialized` no viaja y `${msg.id}` da
// '[object Object]': todos los mensajes compartían ese id y el backend los
// descartaba como duplicados. Este helper arma un id real o devuelve null.
const SERIALIZED = /^(true|false)_[^_\s]+@[a-z.]+_[A-Za-z0-9]+(_[^\s]+)?$/

function jid(value) {
  if (typeof value === 'string') return value
  if (value && typeof value._serialized === 'string') return value._serialized
  return ''
}

function stableMessageId(id) {
  if (typeof id === 'string') return SERIALIZED.test(id) ? id : null
  if (!id || typeof id !== 'object') return null
  for (const candidate of [id._serialized, id.$1]) {
    if (typeof candidate === 'string' && SERIALIZED.test(candidate)) return candidate
  }
  const remote = jid(id.remote)
  if (typeof id.fromMe === 'boolean' && remote && typeof id.id === 'string' && id.id) {
    const composed = `${id.fromMe}_${remote}_${id.id}`
    return SERIALIZED.test(composed) ? composed : null
  }
  return null
}

module.exports = { stableMessageId }
