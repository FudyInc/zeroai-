'use strict'

// Respuesta escrita en la bandeja del panel. whatsapp-web.js puede enviar el
// mensaje y devolver undefined; antes eso terminaba en un 502 con el mensaje ya
// entregado, y quien reintentaba lo duplicaba. Aquí el envío se confirma con
// sendAndConfirm (evento message_create o búsqueda en el chat) y, si no hay
// confirmación, se responde 202: resultado desconocido, nunca un reintento.

const UNCONFIRMED = 'WhatsApp no confirmó el envío. Revisa el chat antes de reenviar.'

async function sendInboxReply(chatId, text, { sendAndConfirm, resolvePhone, now = () => Math.floor(Date.now() / 1000) }) {
  const confirmed = await sendAndConfirm(chatId, text, {},
    message => message.type === 'chat' && String(message.body || '').trim() === text, 'chat', text)
  let phone = null
  try {
    phone = await resolvePhone(chatId)
  } catch (_) { phone = null }
  if (!/^\d{8,15}$/.test(phone || '')) phone = null
  if (!confirmed?.id) {
    return { status: 202, body: { message: null, confirmed: false, phone, warning: UNCONFIRMED } }
  }
  return {
    status: 200,
    body: {
      message: { id: confirmed.id, body: text, type: 'chat', fromMe: true, ack: confirmed.ack ?? null, timestamp: now(), author: null },
      confirmed: true,
      phone,
    },
  }
}

module.exports = { sendInboxReply, UNCONFIRMED }
