'use strict'

const CHAT_ID = /^\d{8,20}@(c\.us|lid)$/

function recentInbound(messages, nowSeconds, maxAgeSeconds = 1800,
                       limit = Number.MAX_SAFE_INTEGER) {
  const seen = new Set()
  return (Array.isArray(messages) ? messages : [])
    .filter(message => {
      if (!message || message.fromMe || typeof message.id !== 'string' || !message.id ||
          typeof message.from !== 'string' || !CHAT_ID.test(message.from) ||
          !Number.isFinite(message.timestamp) ||
          message.timestamp < nowSeconds - maxAgeSeconds ||
          message.timestamp > nowSeconds + 60 || seen.has(message.id)) return false
      if (Number.isFinite(message.lastOutgoingTimestamp) &&
          message.timestamp < message.lastOutgoingTimestamp) return false
      seen.add(message.id)
      return true
    })
    .sort((a, b) => a.timestamp - b.timestamp)
    .slice(-limit)
}

module.exports = { recentInbound }
