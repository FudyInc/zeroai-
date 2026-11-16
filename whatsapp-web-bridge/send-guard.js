'use strict'

// La lectura se hace después de esperar el indicador de escritura.
async function sendGuarded(body, { typing, latestId, send, now = () => Date.now() / 1000 }) {
  await typing()
  if (body.expected_last_id !== undefined || body.expires_at !== undefined) {
    if (!Number.isFinite(body.expires_at) || now() > body.expires_at) {
      throw Error('Mensaje antiguo; revisar antes de responder')
    }
    if (!body.expected_last_id || await latestId() !== body.expected_last_id) {
      throw Error('El chat cambió durante el envío; revisar antes de responder')
    }
    // La consulta del chat también puede tardar.
    if (now() > body.expires_at) throw Error('Mensaje antiguo; revisar antes de responder')
  }
  return send()
}

module.exports = { sendGuarded }
