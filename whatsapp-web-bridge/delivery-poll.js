'use strict'

function serializedVoterId(voter) {
  if (typeof voter === 'string') return voter
  return typeof voter?._serialized === 'string' ? voter._serialized : ''
}

module.exports = { serializedVoterId }
