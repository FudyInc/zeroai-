'use strict'

const assert = require('node:assert/strict')
const { polls, pollForQuestion } = require('./poll-definitions')

for (const [name, poll] of Object.entries(polls)) {
  assert.equal(pollForQuestion(poll.question, [...poll.options]), name)
  // Votos de encuestas enviadas en «tú» antes del 2026-11-11.
  for (const legacy of poll.legacyQuestions || []) {
    assert.equal(pollForQuestion(legacy, [...poll.options]), name)
  }
  assert.doesNotMatch(poll.question, /prefieres|estás|\btu\b/)
}
assert.equal(pollForQuestion('¿Qué color prefiere?', ['Rojo']), null)
console.log('poll definitions OK')
