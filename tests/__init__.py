"""La suite no escribe en los datos de producción.

`unittest discover` importa este paquete antes que cualquier test, así que es el único
punto donde se puede aislar a TODA la suite de una vez — sin depender de que cada archivo
se acuerde.

Motivo medido (2026-09-08): al construir el detector de mocks de `revisar-salud.py`
apareció que la suite escribe en `agent_activity.json`, el MISMO archivo de telemetría
que usa producción. En una ventana de 45 minutos había 197 eventos en mock, y los 197
eran de la suite y de la auditoría — con `client_id` inventados por los propios tests
(`listable`, `vocabulario`, `veloz`). Un detector que mira ahí grita todos los días por
trabajo que nadie hizo, y un aviso que suena siempre se ignora justo el día que importa.

Solo se redirige la telemetría. `crm.json`, `state.json` y compañía ya los aíslan los
tests que los usan, cada uno con su temporal.
"""
import os
import tempfile

# Un archivo por corrida de la suite, en el temporal del sistema. No se borra al terminar
# a propósito: si un test falla por lo que registró, el rastro queda para poder mirarlo.
os.environ.setdefault(
    "AGENT_TELEMETRY_PATH",
    os.path.join(tempfile.gettempdir(), f"zero-telemetria-tests-{os.getpid()}.json"),
)
