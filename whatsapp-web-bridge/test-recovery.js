'use strict'

const assert = require('node:assert/strict')
const { recentInbound } = require('./recovery')

const now = 10000
const messages = [
  { id: 'old', from: '56911111111@c.us', fromMe: false, timestamp: 1000 },
  { id: 'newer', from: '56911111111@lid', fromMe: false, timestamp: 9999 },
  { id: 'outbound', from: '56911111111@lid', fromMe: true, timestamp: 9998 },
  { id: 'group', from: '123456789@g.us', fromMe: false, timestamp: 9997 },
  { id: 'earlier', from: '56911111111@c.us', fromMe: false, timestamp: 9990 },
  { id: 'newer', from: '56911111111@lid', fromMe: false, timestamp: 9999 },
  { id: 'future', from: '56911111111@lid', fromMe: false, timestamp: 10090 },
  { id: 'answered', from: '56911111111@lid', fromMe: false,
    timestamp: 9995, lastOutgoingTimestamp: 9996 },
  { id: 'unanswered', from: '56911111111@lid', fromMe: false,
    timestamp: 9997, lastOutgoingTimestamp: 9996 },
  { id: 'same-second', from: '56911111111@lid', fromMe: false,
    timestamp: 9996, lastOutgoingTimestamp: 9996 },
]

assert.deepEqual(recentInbound(messages, now).map(message => message.id),
  ['earlier', 'same-second', 'unanswered', 'newer'])
assert.deepEqual(recentInbound(messages, now, 7200, 1).map(message => message.id), ['newer'])
assert.deepEqual(recentInbound(null, now), [])
console.log('recovery selection OK')
