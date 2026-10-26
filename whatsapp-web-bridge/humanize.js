'use strict'

// 8000 is a transport safety cap; the delivery policy lives in
// zero/config.py WHATSAPP_HUMAN_DELIVERY.
const MAX_TYPING_MS = 8000

function safeTypingMs(value) {
  const n = typeof value === 'number' ? value : Number.NaN
  if (!Number.isFinite(n) || n <= 0) return 0
  return Math.min(Math.floor(n), MAX_TYPING_MS)
}

module.exports = { safeTypingMs, MAX_TYPING_MS }
