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

// Casos del módulo «Atención» (lo que el agente no pudo resolver). Un caso vuelve a
// avisar si se repite: la clave incluye `ultima`.
export const attentionCaseKey = (item) => `${item.clave}:${item.ultima || ''}`

export const openAttentionCases = (items) => (items || []).filter((item) => item && item.estado === 'abierta')

export function unseenAttentionCases(items, seen) {
  return openAttentionCases(items).filter((item) => !seen.has(attentionCaseKey(item)))
}

// «hace 5 min», «hace 2 h», «hace 3 d». `now` se inyecta para poder probarlo.
export function timeAgo(iso, now = Date.now()) {
  const t = Date.parse(iso)
  if (!iso || Number.isNaN(t)) return ''
  const min = Math.max(0, Math.round((now - t) / 60000))
  if (min < 1) return 'hace un momento'
  if (min < 60) return `hace ${min} min`
  if (min < 1440) return `hace ${Math.round(min / 60)} h`
  return `hace ${Math.round(min / 1440)} d`
}
