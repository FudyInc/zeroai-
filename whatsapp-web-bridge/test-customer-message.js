'use strict'

const assert = require('node:assert/strict')
const { isCustomerMessageType } = require('./customer-message')

for (const type of ['chat', 'location', 'image', 'ptt', 'document']) {
  assert.equal(isCustomerMessageType(type), true)
}
for (const type of ['notification_template', 'e2e_notification', 'protocol', 'reaction']) {
  assert.equal(isCustomerMessageType(type), false)
}
console.log('customer message type filter OK')
