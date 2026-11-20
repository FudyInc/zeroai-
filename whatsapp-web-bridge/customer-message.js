'use strict'

const customerTypes = new Set([
  'chat', 'audio', 'ptt', 'image', 'album', 'video', 'document', 'sticker',
  'location', 'vcard', 'multi_vcard', 'order', 'product', 'groups_v4_invite',
  'list_response', 'buttons_response', 'template_button_reply',
  'interactive', 'native_flow',
])

// Avisos que WhatsApp inserta en el chat sin que nadie escriba. El anuncio de
// clic a WhatsApp deja dos «notification_template» un segundo después del primer
// mensaje del cliente (visto 2026-11-20): contarlos como el último mensaje hacía
// que el agente callara ante cada contacto nuevo de un anuncio.
const systemTypes = [
  'notification_template', 'e2e_notification', 'notification', 'gp2',
  'call_log', 'protocol', 'broadcast_notification',
]

function isCustomerMessageType(type) {
  return customerTypes.has(type)
}

module.exports = { isCustomerMessageType, systemTypes }
