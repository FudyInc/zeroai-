# Pedido 2026-11-04 · motor-whatsapp: alarma cuando el motor lee el prompt cortado

Origen: medición del 2026-11-04. Lo toma el terminal motor-whatsapp.

**Lo que se encontró.** Ollama cargaba `qwen3:14b` con su ventana por defecto, 4096
tokens. Nada en el repo ni en el servicio la agrandaba, y el camino OpenAI-compatible
(`/v1/chat/completions`, el que usa `zero/backends.py`) no permite pasar `num_ctx`. Cuando
el prompt no cabía, Ollama lo cortaba **en silencio**: sin error, solo un `WARN
truncating input prompt` en el journal. Entre el 2026-10-27 y el 2026-11-04 el journal
registra **26 cortes** con `limit=2050`, por ejemplo `prompt=4697` → 2050 (el modelo leyó
menos de la mitad).

La ficha que usa producción sale de Supabase y es corta (2 284 caracteres de ficha y
1 179 de precios), así que no todas las conversaciones se cortaban: lo hacían las que,
sumando el historial, pasaban el límite. Cuántas respuestas reales salieron de un prompt
cortado no se sabe con exactitud. Por lo mismo, la línea base del 2026-10-28 queda en
duda. (Una primera medición de este mismo día hablaba de «2 050 de 9 553»; estaba mal
porque usaba `docs/ficha-losetaschile.md`, que no es la ficha de producción.)

Comando que lo demuestra:

```
journalctl -u ollama --since 2026-10-01 --no-pager | grep "truncating input prompt"
```

**Corregido hoy, fuera del repo.** Diego agregó
`Environment="OLLAMA_CONTEXT_LENGTH=16384"` en
`/etc/systemd/system/ollama.service.d/zero.conf`. `ollama ps` muestra ahora CONTEXT 16384,
con 100 % en GPU (11 GB de 16 GB), y un prompt de prueba de 9 553 tokens se lee completo
por `/v1`. Ese ajuste vive en el sistema, no en el repo: si se reinstala Ollama o se
cambia de máquina, se pierde sin aviso.

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
