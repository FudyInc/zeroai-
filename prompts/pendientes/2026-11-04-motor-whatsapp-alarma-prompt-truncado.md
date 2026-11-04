# Pedido 2026-11-04 · motor-whatsapp: alarma cuando el motor lee el prompt cortado

Origen: medición del 2026-11-04. Lo toma el terminal motor-whatsapp.

**Lo que se encontró.** Ollama cargaba `qwen3:14b` con su ventana por defecto, 4096
tokens. Nada en el repo ni en el servicio la agrandaba, y el camino OpenAI-compatible
(`/v1/chat/completions`, el que usa `zero/backends.py`) no permite pasar `num_ctx`. El
prompt del agente de WhatsApp (`prompts/concierge.md` más la ficha de losetaschile) pesa
**9 553 tokens**, pero el modelo leía **2 050**, un 21 %. Ollama corta en silencio: no
devuelve error. Así respondió el agente, sin que nada avisara, hasta esa fecha, y por eso
el 48 % de la línea base del 2026-10-28 no mide al modelo.

Comando que lo demuestra (comparar `usage.prompt_tokens` con el largo real):

```
python3 - <<'EOF'
import json, urllib.request
p = open("prompts/concierge.md").read() + "\n\n" + open("docs/ficha-losetaschile.md").read()
b = {"model":"qwen3:14b","max_tokens":1,"messages":[{"role":"system","content":p},{"role":"user","content":"hola"}]}
r = json.load(urllib.request.urlopen(urllib.request.Request("http://localhost:11434/v1/chat/completions",
    data=json.dumps(b).encode(), headers={"Content-Type":"application/json"}), timeout=300))
print(r["usage"]["prompt_tokens"])
EOF
```

**Corregido hoy, fuera del repo.** Diego agregó
`Environment="OLLAMA_CONTEXT_LENGTH=16384"` en
`/etc/systemd/system/ollama.service.d/zero.conf`. Ahora el modelo lee 9 553 de 9 553 y
`ollama ps` muestra CONTEXT 16384, con 100 % en GPU (11 GB de 16 GB). Ese ajuste vive en
el sistema, no en el repo: si se reinstala Ollama o se cambia de máquina, se pierde sin
aviso.

**Lo que se pide.**
1. `scripts/revisar-salud.py` comprueba que el motor de WhatsApp lee el prompt completo.
   La alarma salta cuando los tokens que el modelo dice haber leído quedan por debajo de
   los que se le enviaron. Se mira el resultado (`usage.prompt_tokens` de una llamada
   real), no la configuración. Avisa por el mismo canal que los demás chequeos y manda
   `/fail` a Healthchecks.
2. El umbral (p. ej. el contexto mínimo aceptable) va en `zero/config.py`, no en el
   script.
3. Dejar documentado en el vault (nota de infraestructura correspondiente) que el
   contexto de Ollama depende de ese archivo de systemd, con el comando para revisarlo.
4. Tests en `tests/` para la alarma (motor que lee completo / motor que lee cortado). La
   suite completa debe quedar en verde.

**No tocar.** El contenido de `prompts/*.md`, `frontend/`, el archivo de systemd (es del
sistema; si hace falta cambiarlo, se le pide a Diego), y los datos `state.json` y
`crm.json`.
