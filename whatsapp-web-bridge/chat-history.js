'use strict'

// Evita getChatById/getChatModel: serializar el chat completo falla en algunas
// versiones de WhatsApp Web, aun cuando su colección y mensajes están disponibles.
async function readChatMessages(page, chatId, limit = 100) {
  if (!/^\d[\d-]{7,39}@(c\.us|lid|g\.us)$/.test(chatId) ||
      !Number.isInteger(limit) || limit < 1 || limit > 100) throw Error('Consulta de chat inválida')
  return page.evaluate(async ({ chatId, limit }) => {
    const chat = window.require('WAWebCollections').Chat.getModelsArray()
      .find(item => item.id?._serialized === chatId)
    if (!chat) throw Error('Chat no encontrado')
    const idOf = item => {
      const id = item.id
      if (typeof id === 'string') return id
      if (typeof id?._serialized === 'string') return id._serialized
      if (typeof id?.$1 === 'string') return id.$1
      const remote = typeof id?.remote === 'string' ? id.remote :
        id?.remote?._serialized || (id?.remote?.user && id?.remote?.server ?
          `${id.remote.user}@${id.remote.server}` : '')
      return typeof id?.fromMe === 'boolean' && remote && typeof id?.id === 'string' && id.id
        ? `${id.fromMe}_${remote}_${id.id}` : null
    }
    const unique = items => {
      const out = new Map()
      for (const item of items.filter(item => !item.isNotification)) {
        const id = idOf(item)
        if (!id || id === '[object Object]') throw Error('Mensaje sin id estable')
        out.set(id, item)
      }
      return [...out.values()]
    }
    let messages = unique(chat.msgs.getModelsArray())
    while (messages.length < limit) {
      const loaded = await window.require('WAWebChatLoadMessages').loadEarlierMsgs({ chat })
      if (!loaded?.length) break
      const merged = unique([...loaded, ...messages])
      if (merged.length <= messages.length) break
      messages = merged
    }
    return messages.sort((a, b) => (a.t || 0) - (b.t || 0)).slice(-limit).map(msg => ({
      id: idOf(msg), type: msg.type || '',
      fromMe: typeof msg.id === 'string' ? msg.id.startsWith('true_') : !!msg.id?.fromMe,
      body: msg.type === 'chat' ? String(msg.body || '') : `[${msg.type || 'archivo'}]`,
      ack: msg.ack ?? null, timestamp: msg.t || 0,
      author: msg.author?._serialized || (typeof msg.author === 'string' ? msg.author : null),
    }))
  }, { chatId, limit })
}

module.exports = { readChatMessages }
