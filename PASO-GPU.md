# Tarea: Docker + Ollama con la RTX 5060 Ti, y subir el modelo local

> Instrucciones para Claude Code corriendo en el PC de Diego (WSL2).
> Este archivo ES la tarea: léelo y ejecútalo.

> ⚠️ **LEE ESTO PRIMERO — te vas a apagar a ti mismo si no lo tienes en cuenta.**
> Corres DENTRO de WSL2. El paso 2 pide `wsl --shutdown`, que mata la distro
> entera **incluida esta sesión tuya**. Ya pasó una vez y se perdió el contexto.
>
> Antes de cualquier `wsl --shutdown`:
> 1. Anota lo que llevas hecho en `PASO-GPU-progreso.md` (créalo si no existe):
>    qué pasos completaste, qué decidiste y por qué, qué falta.
> 2. Dile a Diego que va a cortarse la sesión y que la reabra con `claude`.
>
> **Al iniciar**: si `PASO-GPU-progreso.md` existe, léelo primero y retoma
> desde ahí en vez de empezar de cero.

## OBJETIVO

Dejar Docker y Ollama operativos en WSL2 aprovechando la RTX 5060 Ti 16GB, y
subir el modelo local a uno más capaz ahora que hay VRAM. **Verificado con
mediciones, no con suposiciones.**

## CONTEXTO — decisiones ya tomadas, no re-litigar

- La máquina **sí tiene GPU**: NVIDIA RTX 5060 Ti 16GB (GB206, Blackwell),
  confirmada con `lspci`. En el Ubuntu bare-metal daba pantalla negra porque
  `nouveau` no soporta Blackwell y no había driver propietario instalado.
- **Medición real (2026-07-22)** contra WhatsApp en producción con
  `qwen2.5:7b-instruct-q4_K_M` en CPU: **26-27 segundos por respuesta**.
  Diego lo declaró inaceptable ("no puede fallar, es un dealbreaker").
  Bajar esa latencia es el objetivo de todo esto.
- **Docker va NATIVO en WSL2 vía apt** (Docker Engine), **no** Docker Desktop.
  Razones: el sandbox usa flags de semántica Linux directa; systemd ya
  gestiona los servicios; Docker Desktop reservaría varios GB de los 16 de
  RAM; y no hace falta GUI ni varias distros.
- **Ollama se decide por prueba**, no por opinión — ver paso 4.
- ⚠️ `host.docker.internal` **no existe sin Docker Desktop**. Si Ollama termina
  del lado Windows, hay que llegar por la IP del host o con red en modo
  *mirrored*.

## PASOS

### 1. Driver NVIDIA en Windows
Lo instala Diego a mano (GeForce Experience o nvidia.com). **Requisito para
ambos caminos** — sin esto nada usa la GPU. Confírmale que lo hizo antes de
seguir.

### 2. Arreglar la interop rota
Agregar a `/etc/wsl.conf`, conservando `[boot] systemd=true`:

```ini
[interop]
enabled=true
appendWindowsPath=true
```

Después hace falta `wsl --shutdown` **desde PowerShell** (no desde bash).

⚠️ **Esto te mata a ti también.** Antes de pedírselo a Diego: anota tu progreso
en `PASO-GPU-progreso.md` y avísale que reabra la sesión con `claude` después.

Al reabrir, confirmar que `powershell.exe` corre desde bash y que systemd sigue
siendo PID 1 (`ps -p 1 -o comm=`).

**Alternativa para no cortarte:** deja este paso 2 para el FINAL. La interop no
es requisito de Docker ni de Ollama — solo sirve para lanzar programas de
Windows desde bash. Puedes hacer los pasos 3 al 6 primero, medir todo, y dejar
el reinicio de WSL como último movimiento.

### 3. Docker Engine nativo
Instalar desde el **repositorio oficial de Docker** (no el `docker.io` de
Ubuntu, que va atrasado). Habilitar con systemd, agregar el usuario al grupo
`docker`, y verificar con `docker run --rm hello-world`.

### 4. Decidir dónde va Ollama — con esta prueba

```bash
nvidia-smi
```

- **Si detecta la RTX 5060 Ti** → Ollama nativo en WSL2
  (`curl -fsSL https://ollama.com/install.sh | sh`).
  Es el camino preferido: todo en un lugar, systemd lo gestiona, sin
  complicación de red, y el modelo carga en VRAM en vez de comerse la RAM.
- **Si no la detecta** → Ollama en Windows (instalador `.exe`), con
  `OLLAMA_HOST=0.0.0.0` para que WSL2 lo alcance, y ajustar
  `LOCAL_MODEL_URL` en el `.env` a la IP del host
  (`ip route show default | awk '{print $3}'`).

Reporta cuál camino tomaste y por qué.

### 5. Elegir el modelo nuevo

Punto de partida recomendado: **`qwen2.5:14b-instruct-q4_K_M`** — misma
familia que el actual (los prompts ya están afinados para su comportamiento),
~9GB, entra cómodo en 16GB de VRAM dejando espacio para contexto.

**Antes de descargarlo:** revisa qué hay disponible hoy en la librería de
Ollama (esta recomendación puede estar desactualizada) y evalúa alternativas
del orden de **14B–24B cuantizadas a q4 que quepan en 16GB SIN spill a RAM** —
un modelo que se desborda es más lento que uno más chico que entra entero.

Propón tu elección con el razonamiento **antes** de bajar 9GB.

### 6. Actualizar el `.env`
`LOCAL_MODEL` y `LOCAL_MODEL_URL` en `~/zeroai/.env`.

---

## VERIFICACIÓN — esto es lo que importa, no la instalación

**a) Latencia.** Mide el tiempo real de una respuesta de CONCIERGE por el
**mismo camino que usa producción** (`zero/orchestrator.py::converse_result`
o `handle_inbound`), no con un `ollama run` suelto. Compara contra la línea
base de 26-27s. **Reporta el número.**

**b) Calidad del contrato.** El modelo debe devolver JSON con el esquema
`{"reply","intent"}`. Hay antecedente documentado en `zero/config.py`
(`MAX_INBOUND_MESSAGE_CHARS`): con `qwen2.5:7b`, un mensaje largo y degenerado
hizo que abandonara el esquema e inventara claves propias, dejando la
respuesta **vacía**. Prueba varios mensajes —incluido uno largo— y confirma
que el esquema se respeta.

**c) Español.** Las respuestas deben sonar naturales en español chileno, como
Fernanda. Un modelo que responde mejor en inglés pero raro en español es peor
para este caso, aunque puntúe mejor en benchmarks.

**d) Sandbox.** `python3 -m unittest discover -s tests -t .` en verde (641
tests), **y** una función real ejecutándose en Docker: verifica que
`run_sandboxed` funciona con **todos** sus flags (`--network=none`,
`--cap-drop=ALL`, `--security-opt=no-new-privileges`, `--user`,
`--pids-limit`, `--read-only`, `--tmpfs`). Si alguno falla en WSL2,
repórtalo — es la garantía de seguridad del sistema.

**e) VRAM.** Confirma con `nvidia-smi` que el modelo está en VRAM y cuánta
queda libre. Si se desborda a RAM, baja de tamaño.

## REPORTE

Latencia antes/después, qué modelo elegiste y por qué, dónde quedó Ollama
(WSL2 o Windows) y por qué, y si algún flag del sandbox falla en WSL2.

**Si la latencia sigue sobre ~5s, dilo claramente en vez de darlo por bueno.**
