'use strict'

const customerTypes = new Set([
  'chat', 'audio', 'ptt', 'image', 'album', 'video', 'document', 'sticker',
  'location', 'vcard', 'multi_vcard', 'order', 'product', 'groups_v4_invite',
  'list_response', 'buttons_response', 'template_button_reply',
  'interactive', 'native_flow',
])

function isCustomerMessageType(type) {
  return customerTypes.has(type)
}

module.exports = { isCustomerMessageType }
