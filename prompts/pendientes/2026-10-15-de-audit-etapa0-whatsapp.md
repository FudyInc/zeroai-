# Pedido de AUDIT a PROMPTS — 2026-10-15 · Etapa 0 del agente de WhatsApp

Destino del prompt: **motor-whatsapp**. Diego aprobó arrancar la etapa 0 el 2026-10-15.
Informe completo en `docs/auditoria/2026-10-15.md` (rama `FudyInc/AUDIT`).

## Primero: qué se cerró del pedido anterior (2026-10-06, silencio y contexto)

| Punto | Estado | Comando |
|---|---|---|
| 3 · bloquear «Ya revisé tu consulta» sin evidencia | **cerrado en el checkout de producción** | `grep -n "consulta|cotizaci" /home/diego/zeroai/zero/orchestrator.py` → líneas 139-143 cubren `consulta` |
| 1, 2, 4, 5 | **sin verificar** por AUDIT | no hay prueba de punta a punta registrada después del 2026-10-08 |

No vuelvas a pedir el punto 3.

## Por qué esta etapa: la decisión que hay que tomar

Diego evaluó reemplazar el agente por `Carlos-Dominguez-faber/whatsapp-saas` (MIT, Next.js + Supabase + OpenRouter). **Decisión: no migrar.** El candidato no admite un modelo local y cuesta dinero por mensaje. Antes de culpar a Qwen hay que medirlo, porque hay un defecto de configuración comprobado:

```
$ ollama ps        # tras cargar qwen3:14b con una petición mínima, 2026-10-15
qwen3:14b   9.6 GB   100% GPU   CONTEXT 4096
$ ollama show qwen3:14b | grep context
context length 40960
$ grep -rn "num_ctx\|OLLAMA_CONTEXT_LENGTH" /home/diego/zeroai --include=*.py   # vacío
$ systemctl cat ollama | grep -i environment                                       # solo PATH
```

- El agente carga Qwen con **4096 tokens de contexto**, aunque el modelo admite 40.960.
- El prompt local estimado es de **2.300 a 3.500 tokens**:
  - system prompt de unos 1.000 tokens (`prompts/concierge-whatsapp-local.md`)
  - ficha de hasta 1.600 caracteres
  - 6 turnos de historial
  - instrucciones de hasta 1.200 caracteres
- A eso se suma el razonamiento de qwen3, que está activo porque `zero/backends.py:77` solo apaga `think` para modelos r1, qwq y deepseek.
- **Hipótesis principal:** Ollama recorta el inicio del prompt (las reglas) en las conversaciones más largas. Los incidentes del 7 de octubre (respuestas inventadas, «ya revisé…») encajan con eso. La etapa 0 existe para confirmarlo o descartarlo con números.

## Lo que pido: etapa 0, medir sin cambiar nada

**Objetivo:** una línea base reproducible del agente **tal como está hoy**, para comparar contra ella cada cambio de las etapas siguientes (contexto, razonamiento, temperatura, modelo).

1. **Set de evaluación.**
   - 30 a 50 conversaciones reales, exportadas en **solo lectura** desde el historial (`state.json` o la tabla de memoria en Supabase).
   - Anonimizadas: nombres, teléfonos, direcciones y correos reemplazados.
   - Deben incluir los incidentes conocidos: «Necesito pastelones» → «alrededor de 18», «Ya revisé tu consulta», el chat pausado por «consulta no interpretable», y la pregunta de medidas desde un chat sin historial.
   - Al repo solo entran datos anonimizados. Los crudos no se commitean.
2. **Arnés de reproducción.**
   - Un script que pase cada conversación por el mismo camino de producción (`Zero.handle_inbound` / `converse_result`) **sin envío real**: `OUTBOX_LIVE` apagado, sin puente y sin Supabase de producción.
   - Por cada turno debe registrar: respuesta, `intent`, si hubo handoff, rechazos de las reglas posteriores al modelo y latencia.
   - Debe registrar también los tokens del prompt según Ollama (`prompt_eval_count`, vía `/api/chat`, o los logs del servicio) y **si Ollama truncó la entrada** (`journalctl -u ollama | grep -i truncat`).
3. **Rúbrica.**
   - Checks automáticos: cifras inventadas, afirmaciones de revisión sin evidencia, volver a pedir datos que ya se dieron, handoff indebido.
   - Revisión humana de una muestra: corrección y tono chileno.
   - Para puntuar se puede usar la suscripción de Claude o Codex, porque es uso de desarrollo y no atiende a nadie.
4. **Entregable.**
   - El script y su test en `motor-whatsapp`.
   - Un informe `docs/evaluacion/2026-10-XX-linea-base.md` con la tabla de resultados por conversación y los agregados: % de respuestas correctas, % de inventos, % de handoff y latencia p50/p95.
   - El informe debe decir explícitamente si hubo truncado y en qué % de los turnos.

## Restricciones duras

- **No cambiar configuración en esta etapa.** Nada de `num_ctx`, `think` ni temperatura en el código, y nada de `OLLAMA_CONTEXT_LENGTH` en el servicio: el Ollama es el mismo que atiende producción. Esos cambios son la etapa 1 y se prueban contra esta línea base.
- No tocar `/home/diego/zeroai`. Es producción, con trabajo sin commitear de otras sesiones, y ahí viven `state.json`, `crm.json` y las credenciales. Trabajar en una copia aislada; ver la memoria *Worktree del backend activo*.
- No enviar mensajes, no tocar webhooks, números ni credenciales.
- La GPU es compartida con producción: correr el set en horario de poco tráfico o en tandas cortas.
- Solo stdlib en el núcleo. El arnés tampoco agrega dependencias.

## Condición de cierre

1. El script reproduce el set completo con el agente actual y deja resultados en disco.
2. El informe trae números, no impresiones, y responde con evidencia: **¿hay truncado de contexto con la configuración actual?**
3. Suite de tests en verde.
4. El resultado queda en un commit de `motor-whatsapp` y se avisa a PROMPTS con el hash.
