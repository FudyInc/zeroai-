import test from 'node:test'
import assert from 'node:assert/strict'
import { architectureActivity } from './architecture-activity.js'

test('la vista operativa no presenta fixtures como actividad o motores reales', () => {
  const engines = ['mock', "<Mock name='mock.primary.model'>", 'ScriptedBackend', 'BoomBackend', 'qwen2.5:14b', 'OpenAIBackend']
  const data = { recientes: engines.map((engine, i) => ({ agent: 'PROSPECTOR', engine, ms: i * 100, status: i === 5 ? 'error' : 'done' })), eventos: 200, agentes: [{ agent: 'CONCIERGE', corridas: 190 }] }
  const result = architectureActivity(data)
  assert.equal(result.eventos, 2)
  assert.equal(result.agentes.length, 1)
  assert.equal(result.agentes[0].corridas, 2)
  assert.equal(result.agentes[0].errores, 1)
  assert.deepEqual(result.agentes[0].engines, ['qwen2.5:14b', 'OpenAIBackend'])
  assert.equal(data.recientes.length, 6)
})

test('no oculta errores sin motor informado', () => {
  const result = architectureActivity({ recientes: [{ agent: 'PROSPECTOR', status: 'error' }] })
  assert.equal(result.eventos, 1)
  assert.equal(result.agentes[0].errores, 1)
  assert.deepEqual(result.agentes[0].engines, [])
})

test('sin ejecuciones reales la vista queda sin actividad', () => {
  assert.deepEqual(architectureActivity().agentes, [])
  assert.equal(architectureActivity({ recientes: [{ engine: 'mock' }] }).eventos, 0)
})
