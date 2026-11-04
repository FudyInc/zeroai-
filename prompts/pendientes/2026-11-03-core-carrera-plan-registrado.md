# Pedido 2026-11-03 · CORE: carrera que borra el plan del cliente (test intermitente)

Origen: terminal motor-whatsapp, al subir el trabajo de CORE a main el 2026-11-03.

Evidencia: `tests.test_api_http.OperadorAislamientoHttpTest.test_runs_y_progress_filtrados_al_alcance` falla 2 de cada 12 corridas **en main**, antes de los commits de CORE. Cuando falla, la segunda llamada responde:

```
POST /api/pipeline/start (admin, cliente ajeno)  → 200 {'run': 'r_…', 'cliente': 'acme', …}
POST /api/pipeline/start (operador, cliente propio) → 409 {'detail': 'el cliente no tiene un plan registrado'}
```

El cliente propio se registra en setUp. La primera corrida arranca en segundo plano y, unos milisegundos después, el plan del segundo cliente «desaparece». Hipótesis: la corrida en segundo plano guarda `state.json` partiendo de una copia anterior y pisa el registro, o se lee el archivo a medio escribir. Si es eso, en producción también puede perder datos de un cliente cuando dos corridas se cruzan.

```
PASO 0: git fetch && git rebase origin/main.

[TARGET: ⚙️ CORE]

TAREA — encontrar y cerrar la carrera, no el test.
- Reprodúcela de forma determinista (por ejemplo, forzando el orden con un evento), y no con un bucle de reintentos.
- Arregla la causa en el mecanismo de guardado o lectura (zero/memory.py / zero/store.py / api.py), sin tocar config.py.
- No subas el timeout del test ni agregues reintentos: eso tapa el problema (principio 1).
- Test: el caso determinista falla antes del arreglo y pasa después. El test original, 30 corridas seguidas sin fallar.

ACEPTACIÓN: suite completa en verde y 30 de 30 en el test original.
REPORTE: causa con evidencia, el arreglo y si producción pudo perder datos por esto.
```
