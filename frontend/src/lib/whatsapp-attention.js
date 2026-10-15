const REVIEW_NOTICE = 'Necesito revisar tu consulta antes de responderte bien; quedó pendiente en este chat.'

export const attentionOf = (chat, responseMode = 'automatic') => {
  if (chat?.handoff) return { reason: chat.handoff.reason || 'Atención humana', key: chat.handoff.at || chat.handoff.reason || '' }
  if (chat?.lastFromMe && String(chat.lastMessage || '').includes(REVIEW_NOTICE)) {
    return { reason: 'El agente dejó una consulta pendiente de revisión', key: `review:${chat.timestamp || ''}` }
  }
  if (responseMode === 'manual' && !chat?.isGroup && !chat?.lastFromMe && chat?.unreadCount > 0) {
    return { reason: 'Mensaje nuevo en atención manual', key: `manual:${chat.timestamp || ''}` }
  }
  return null
}

export const humanChats = (chats, responseMode) => (chats || []).filter((chat) => !!attentionOf(chat, responseMode))

export const inboxNavigationKey = (client, account, locationKey, request) =>
  JSON.stringify([client, account, locationKey, request])

export const handoffKey = (chat, responseMode) => `${chat.id}:${attentionOf(chat, responseMode)?.key || ''}`

export const needsPopup = (chat, responseMode) => !!attentionOf(chat, responseMode) && !/^El equipo (tomó|respondió)/.test(chat.handoff?.reason || '')

export function unseenHumanRequests(chats, seen, responseMode) {
  return humanChats(chats, responseMode).filter((chat) => needsPopup(chat, responseMode) && !seen.has(handoffKey(chat, responseMode)))
}
