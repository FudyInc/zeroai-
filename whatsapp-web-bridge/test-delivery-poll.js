'use strict'

const assert = require('node:assert/strict')
const { serializedVoterId } = require('./delivery-poll')

assert.equal(serializedVoterId({ _serialized: '56912345678@c.us' }), '56912345678@c.us')
assert.equal(serializedVoterId('56912345678@lid'), '56912345678@lid')
assert.equal(serializedVoterId({}), '')
console.log('delivery poll voter normalization OK')
