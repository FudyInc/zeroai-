# Pedido de AUDIT a PROMPTS — el ciclo autónomo tiene que verse en el dashboard

Segundo pedido del 2026-09-05, aparte del de F1/M1/carril-1. Este viene de una idea de
Diego —mirar el catálogo de [AI SDK Elements](https://elements.ai-sdk.dev)— pero lo que
lo justifica no es el catálogo: es un fallo que está medido en `docs/auditoria/`.

## El problema, con su evidencia

**El ciclo autónomo estuvo ocho días sin ejecutar una sola tarea y nadie se enteró.**
Del 2026-08-29 al 2026-09-05: abortó el 30, el 1, el 2, el 3 y el 4; no corrió el 31.

```
$ journalctl --user -u zero-dia.service --since <cualquiera de esos días> | grep -ci aviso
0
```

Mientras tanto la cola creció sola: **10 → 12 → 15 → 17 → 19 pendientes**, y llegó a
tener siete versiones de la misma tarea. Nada de eso era visible en ninguna parte.

La causa inmediata ya está pedida aparte (F1: que el aborto avise antes del `return 2`).
Pero un aviso es un empujón puntual — **no responde "¿qué hizo el ciclo esta semana?"**.
Hoy la única forma de saberlo es `journalctl`, y el propio repo ya reconoce el problema en
`scripts/sincronizar-workspaces.sh`:

> *"El journal de systemd no lo lee nadie."*

Ese comentario está ahí desde antes y describe exactamente lo que pasó.

## Lo que ya existe (no lo rehagas — verifica antes de proponer)

Los datos están, con detalle de sobra. Lo que falta es exponerlos y dibujarlos.

```
zero/tasks.py       cada tarea trae: estado, intentos, rama, commit, veredicto del juez,
                    e historial completo [{ts, estado, detalle}, …]
zero/telemetry.py   registrar() / eventos() / resumen() — qué agente, con qué motor, cuántos ms
audit/diaria        docs/auditoria/YYYY-MM-DD.json — el informe mecánico de cada día
auditoria.json      el del día en curso, con hallazgos + evidencia
```

Endpoints que **ya existen** en `api.py`:

```
/api/agents/telemetry      (línea 1878)
/api/conductor/status | roles | sessions | sessions/{id} | …   (2027–2101)
/api/health                (367)
```

Endpoints que **no existen**: ninguno sobre `zero.tasks` ni sobre el resultado de la
tanda. Lo comprobé:

```
$ grep -nE "^@app\.(get|post)" api.py | grep -iE "task|tarea|tanda|cola|ciclo|audit"
(sin resultados)
```

Y en el dashboard no hay ninguna pantalla del ciclo autónomo. `Conductor.jsx` (142
líneas) es otra cosa: sesiones del Conductor, no la tanda.

## Lo que pido

**Dos trabajos, en dos workspaces. El de `core` va primero: el de `dashboard` no puede
empezar sin el endpoint.**

### A · core — exponer el estado del ciclo

Un endpoint (o dos, tú decides la forma) que devuelva lo suficiente para dibujar la vista:

- La cola: `tasks.resumen()` y `tasks.listar()`, con el `historial` de cada tarea — que es
  lo que permite reconstruir la línea de tiempo de un intento.
- El veredicto del juez y el commit resultante, que ya están en la tarea.
- El informe mecánico del día (`auditoria.json`), y ojalá los de días anteriores desde
  `audit/diaria` — ahí está la respuesta a *"¿esto lleva tres semanas roto o se rompió
  anoche?"*, que es literalmente por lo que se creó esa rama (`68bf54b`).

Restricciones: núcleo solo stdlib; los números de negocio en `config.py`; `tareas.json` es
dato local, así que el endpoint **lee, no escribe**. Y va bajo login como el resto — esto
no es `/api/public/*`.

### B · dashboard — la vista

Tres bloques, y el orden es de mayor a menor valor:

1. **Resultado de la última tanda** — por tarea: agente, duración, tests en verde/rojo, el
   veredicto del juez y el commit. Hoy eso solo se lee en el journal.
2. **Historial de salud** — los `hallazgos` por día desde `audit/diaria`. Responde si algo
   lleva semanas roto.
3. **Estado de la cola** — abiertas, atascadas, y la traza de intentos de cada tarea.

Referencia de estructura: las familias **Code** (`Terminal`, `Test Results`, `Stack
Trace`) y **Chatbot** (`Task`, `Tool`) de AI SDK Elements. Míralas para robar la
**estructura**, no la piel.

## Tres restricciones que no son negociables

**1 · No instalar shadcn/ui.** AI SDK Elements está construido encima de shadcn. ZERO
tiene Tailwind v4 pero no shadcn (no hay `components.json`), y sí tiene sus primitivas en
`frontend/src/components/ui.jsx`: `Card`, `Button`, `Badge`, `Eyebrow`, `SectionTitle`,
`Input`, `Select`, `Spinner`, `Skeleton`, `CountUp`, `DropdownSelect`, `pageState`.
Instalar shadcn mete un segundo sistema de diseño compitiendo con el que ya existe. La
regla del repo es extender, no reinventar.

**2 · Sin dependencias nuevas.** Los tres componentes de referencia son layout: no
necesitan React Flow ni nada. (La familia Workflow —`Canvas`, `Connection`, `Node`— sí lo
necesitaría, y por eso queda fuera de este pedido.)

**3 · Nada de estética genérica de app de IA.** Es un requisito explícito de Diego. Usar
el lenguaje visual que ya está en `ui.jsx` y `lib/motion.js`.

## Una decisión que te dejo a ti

El dashboard tiene **18 páginas**. Esto puede ser la 19ª, o una sección dentro de
`Agentes.jsx` o `Conductor.jsx`. No lo decido yo: tú ves los siete workspaces y el repo
dice que cada feature es un pasivo. Si tu conclusión es que cabe dentro de una página
existente, mejor — dilo y arma el prompt así.

## Lo que NO pido, y por qué

Del catálogo de Elements evalué todo. Queda fuera:

- **Conversation, Message, Attachments** → `Whatsapp.jsx` (547 líneas) y `ChatDetail.jsx`
  ya funcionan. Reemplazarlos no compra nada y arriesga el look genérico.
- **Voice (Audio Player, Transcription, Persona)** → Vapi y ElevenLabs están en pendientes
  **de pago**, y `zero/voice.py` sigue con su `TODO(asset real)`. Sería UI para algo
  desconectado.
- **Canvas / Connection / Node / Edge** → es lo más vistoso y sería la vista del pipeline
  en vivo, pero trae React Flow y hoy `Conductor.jsx` tiene 142 líneas: sería construir la
  página, no mejorarla. Vale la pena, más adelante y como decisión aparte.
- **Model Selector, Prompt Input, Suggestion, Queue, Plan, Checkpoint** → patrones de
  producto-chatbot. ZERO no lo es.
- **Confirmation** (encaja con `Aprobar.jsx`) y **Task/Tool** (encajan con la telemetría
  que ya existe) sí valen, pero después de esto. Los menciono para que no se pierdan.
