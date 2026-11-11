'use strict'

const polls = Object.freeze({
  product: Object.freeze({
    question: '¿Qué producto está buscando?',
    legacyQuestions: Object.freeze(['¿Qué producto estás buscando?']),
    options: Object.freeze(['Bordes de piscina', 'Pastelones']),
  }),
  color: Object.freeze({
    question: '¿Qué color prefiere?',
    legacyQuestions: Object.freeze(['¿Qué color prefieres?']),
    options: Object.freeze(['Anaranjado', 'Blanco', 'Rojo', 'Crema', 'Beige', 'Gris', 'Amarillo']),
  }),
  delivery: Object.freeze({
    question: '¿Cómo prefiere recibir su pedido?',
    legacyQuestions: Object.freeze(['¿Cómo prefieres recibir tu pedido?']),
    options: Object.freeze([
      '📍 Despacho · compartir ubicación',
      '✍️ Despacho · escribir dirección',
      '🏭 Retiro en fábrica',
    ]),
  }),
})

function pollForQuestion(question, options) {
  return Object.entries(polls).find(([, poll]) =>
    // Las encuestas enviadas en «tú» antes del 2026-11-11 siguen recibiendo votos.
    (poll.question === question || (poll.legacyQuestions || []).includes(question)) &&
    poll.options.length === options.length && poll.options.every(option => options.includes(option)))?.[0] || null
}

module.exports = { polls, pollForQuestion }
