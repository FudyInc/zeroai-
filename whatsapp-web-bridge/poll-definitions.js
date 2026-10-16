'use strict'

const polls = Object.freeze({
  product: Object.freeze({
    question: '¿Qué producto estás buscando?',
    options: Object.freeze(['Bordes de piscina', 'Pastelones']),
  }),
  color: Object.freeze({
    question: '¿Qué color prefieres?',
    options: Object.freeze(['Anaranjado', 'Blanco', 'Rojo', 'Crema', 'Beige', 'Gris', 'Amarillo']),
  }),
  delivery: Object.freeze({
    question: '¿Cómo prefieres recibir tu pedido?',
    options: Object.freeze([
      '📍 Despacho · compartir ubicación',
      '✍️ Despacho · escribir dirección',
      '🏭 Retiro en fábrica',
    ]),
  }),
})

function pollForQuestion(question, options) {
  return Object.entries(polls).find(([, poll]) => poll.question === question &&
    poll.options.length === options.length && poll.options.every(option => options.includes(option)))?.[0] || null
}

module.exports = { polls, pollForQuestion }
