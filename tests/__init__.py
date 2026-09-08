"""La suite no escribe en la telemetría de la máquina.

`telemetry.registrar()` persiste en `agent_activity.json` relativo al directorio de
trabajo, y la suite se corre desde la raíz del repo — o sea, sobre el mismo archivo que
alimenta el panel de Arquitectura. El resultado, comprobado el 2026-09-08: de los 200
registros del anillo, 193 eran de una corrida de tests (motores `ScriptedBackend`,
`BoomBackend` y hasta el repr de un `unittest.mock.Mock`; clientes `veloz`,
`vocabulario`, `listable`), y el panel mostraba a CONCIERGE como "Mock · simulación"
cuando el concierge real corre sobre qwen2.5:14b. La instrumentación mentía sobre el
sistema que instrumenta.

`AGENT_TELEMETRY_PATH` ya existía como escotilla y `test_telemetry.py` la usaba para sus
propios casos; lo que faltaba era el default para TODA la suite. Va acá y no en
`telemetry.py` porque el módulo no tiene por qué saber que existen los tests: el que
tiene que aislarse es quien corre.

`setdefault` y no asignación directa: si alguien exporta la variable para inspeccionar
una corrida, su valor manda.
"""
import os

os.environ.setdefault("AGENT_TELEMETRY_PATH", os.devnull)
