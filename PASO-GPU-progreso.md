# Progreso — PASO-GPU.md

Última actualización: 2026-08-03, por auditoría de estado real (no había bitácora previa).

## Completado

- **Paso 1 — Driver NVIDIA en Windows:** confirmado. `nvidia-smi` dentro de WSL2
  detecta `NVIDIA GeForce RTX 5060 Ti`, 16311MiB VRAM total, 797MiB en uso, driver
  610.57.01 / CUDA UMD 13.3.
- **Paso 2 — Interop + `wsl --shutdown`:** confirmado. `/etc/wsl.conf` tiene
  `[boot] systemd=true` y `[interop] enabled=true / appendWindowsPath=true`.
  `ps -p 1 -o comm=` devuelve `systemd`. `powershell.exe` corre desde bash sin
  problema. El shutdown ya ocurrió (por eso la sesión anterior se cortó).

- **Paso 3 — Docker Engine nativo:** instalado desde el repo oficial de Docker
  (`docker-ce`, `docker-ce-cli`, `containerd.io`, `docker-buildx-plugin`,
  `docker-compose-plugin`, versión 29.7.1). Servicio habilitado y activo con
  systemd. Usuario `diego` agregado al grupo `docker` (requiere relogin para
  que aplique sin `sudo`). Verificado con `docker run --rm hello-world` → OK.
  Nota: para instalarlo se creó `/etc/sudoers.d/zeroai-temp` (NOPASSWD ALL,
  temporal) porque `sudo` no aceptaba contraseña por el canal no interactivo;
  **hay que borrarlo (`sudo rm /etc/sudoers.d/zeroai-temp`) al terminar toda
  la tarea de PASO-GPU.md.**

- **Paso 4 — Decidir Ollama:** COMPLETADO. Instalado nativo en WSL2
  (`curl -fsSL https://ollama.com/install.sh | sh`, requirió instalar `zstd`
  primero). Servicio systemd activo. Logs confirman detección GPU vía CUDA:
  `NVIDIA GeForce RTX 5060 Ti`, compute=12.0, driver=13.3, total="15.9 GiB",
  available="14.8 GiB". Ollama versión 0.32.5.
- **Paso 5 — Elegir modelo nuevo:** COMPLETADO. Elegido
  `qwen2.5:14b-instruct-q4_K_M` (9.0GB, descargado y verificado con
  `ollama list`). Se evaluó también Qwen3:14b, gpt-oss:20b, mistral-small —
  descartados: Qwen3 trae "thinking mode" activado por defecto en Ollama (no
  está en la lista `no_think` de `zero/backends.py`, que solo reconoce
  `r1`/`qwq`/`deepseek`), lo que agregaría latencia justo en contra del
  objetivo; los otros cambian de familia y arriesgan la calidad del contrato
  JSON / español ya afinada para Qwen2.5.
- **Paso 6 — Actualizar `.env`:** COMPLETADO. `LOCAL_MODEL=qwen2.5:14b-instruct-q4_K_M`
  en `~/zeroai/.env`. `LOCAL_MODEL_URL` sin cambios (`http://localhost:11434/v1`,
  ya apunta a Ollama nativo en WSL2).
## Verificación (a-e) — COMPLETADA

Medido con `zero/orchestrator.py::Zero.converse_result` real (no `ollama run`
suelto), backend `LocalBackend` contra `qwen2.5:14b-instruct-q4_K_M`.

- **(a) Latencia:** primera llamada 33.4s (carga en frío del modelo a VRAM).
  Las 3 siguientes, con modelo ya cargado ("warm"): **1.3s, 1.4s, 1.7s**.
  Baseline previo (qwen2.5:7b en CPU): 26-27s por respuesta. Mejora de
  ~15-20x en estado warm. `OLLAMA_KEEP_ALIVE` por defecto es 5 min, así que
  producción se mantiene warm mientras haya tráfico regular.
- **(b) Contrato JSON:** las 4 pruebas (saludo, pricing, optout, mensaje
  largo degenerado de "hola " x3000) devolvieron `{"reply","intent"}` bien
  formado. El caso documentado en `config.py`/`MAX_INBOUND_MESSAGE_CHARS`
  (7b abandonaba el esquema con mensajes largos) **no se repitió** con 14b.
- **(c) Español:** respuestas naturales en español chileno, tono de
  Fernanda ("¡Hola! Soy Fernanda de ZeroAI...", "Si en algún momento
  necesitas algo, sabes dónde encontrarme").
- **(d) Sandbox:** `python3 -m unittest discover -s tests -t .` → **641
  tests OK**. `RealDockerTest` corrió contra Docker real (tuvo que activarse
  el grupo `docker` con `sg docker` en la sesión, ya que el `usermod` recién
  aplicado requiere relogin) con **todos** los flags: `--network=none`,
  `--cap-drop=ALL`, `--security-opt=no-new-privileges`, `--user 1000:1000`,
  `--pids-limit`, `--read-only`, `--tmpfs`. Ninguno falló en WSL2.
- **(e) VRAM:** `nvidia-smi` confirma el modelo cargado en VRAM (proceso
  `/llama-server`): **9971 MiB usados de 16311 MiB, 6080 MiB libres**. Sin
  spill a RAM.

## Limpieza

- `/etc/sudoers.d/zeroai-temp` (NOPASSWD ALL temporal, usado para instalar
  Docker/Ollama sin bloquear en el prompt de contraseña no interactivo) fue
  **borrado**. `sudo` vuelve a pedir contraseña normalmente.

## Pendiente / a criterio de Diego

- El usuario `diego` quedó agregado al grupo `docker`, pero el cambio recién
  aplica del todo tras un relogin de la sesión de Linux (no hace falta
  `wsl --shutdown`, con cerrar y reabrir la terminal WSL basta).
- Nada más pendiente de PASO-GPU.md. Tarea completa.
