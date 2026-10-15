'use strict'

// Some operations belong to one business only: the pool delivery poll, its vote
// and the per-category catalog PDF are all LosetasChile's. The bridge checks the
// account it runs as before accepting them.
//
// A bridge started per business carries WHATSAPP_WEB_CLIENT_ID; the default one
// (zero/whatsapp_web.py::_bridge_loop) carries nothing, and that is the bridge
// LosetasChile actually runs on — which is why a strict equality check rejected
// every catalog PDF with 403 while the unguarded image route kept working.
//
// An unnamed bridge is therefore allowed. This is not where the real
// authorization lives: whatsapp_web.send_catalog_document refuses any other
// client_id, and _verified_account requires the connected WhatsApp number to be
// the one configured for the business before any request reaches here.
function actsFor(clientId, business) {
  if (!business) return false
  return !clientId || clientId === business
}

module.exports = { actsFor }
