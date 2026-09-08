import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

/* Toda pantalla que muestre salida de `_agent_op` tiene que decir de qué motor salió.
 *
 * `_agent_op` (api.py:992) cae al mock cuando el modelo real falla o devuelve vacío, y
 * devuelve `mode` justo para que la UI lo pueda decir. Forecast.jsx recibía ese dato y lo
 * ignoraba: un forecast simulado se veía idéntico a uno real, que es el mismo defecto que
 * 986daca cerró en Finanzas y Campañas el 2026-09-07.
 *
 * LO QUE ESTE TEST NO HACE, dicho de frente: la lista es a mano. Una pantalla NUEVA que
 * consuma `_agent_op` y no se agregue acá no la va a atrapar nadie. No encontré forma
 * honesta de derivar la lista —`api.js` no marca qué llamadas devuelven `mode`—, así que
 * esto ataja la regresión de las cuatro que existen hoy, no la omisión futura. Si mañana
 * aparece una quinta, agrégala acá.
 */

const raiz = join(dirname(fileURLToPath(import.meta.url)), '..')

// (archivo, endpoint que consume) — los cuatro consumidores de _agent_op al 2026-09-08.
const PANTALLAS = [
  ['pages/Forecast.jsx', 'GET /api/forecast'],
  ['pages/Campanas.jsx', 'POST /api/campaigns/optimize'],
  ['pages/Vender.jsx', 'POST /api/pitch'],
  ['components/AgentTester.jsx', 'POST /api/whatsapp/simulate'],
]

test('las pantallas que muestran salida de agentes declaran el motor', () => {
  for (const [archivo, endpoint] of PANTALLAS) {
    const fuente = readFileSync(join(raiz, archivo), 'utf8')
    assert.ok(
      /\bmode\b/.test(fuente),
      `${archivo} (${endpoint}) no menciona 'mode': si cae al mock, muestra cifras simuladas como si fueran reales`,
    )
  }
})

test('el modo se usa para distinguir, no solo se recibe', () => {
  // Recibir `mode` y guardarlo en un estado que nadie lee es el mismo bug con más pasos.
  // Cada pantalla tiene que comparar el valor contra 'live' o contra 'mock'.
  for (const [archivo] of PANTALLAS) {
    const fuente = readFileSync(join(raiz, archivo), 'utf8')
    assert.ok(
      /mode\s*===\s*'(live|mock)'|mode\s*!==\s*'(live|mock)'/.test(fuente),
      `${archivo} recibe 'mode' pero no lo compara con 'live' ni 'mock'`,
    )
  }
})
