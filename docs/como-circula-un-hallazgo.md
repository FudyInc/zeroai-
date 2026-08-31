# Cómo circula un hallazgo

Qué hace AUDIT con lo que encuentra, y por qué no lo manda por mensaje.

## El problema que esto resuelve

Entre el 28 y el 30 de agosto de 2026, AUDIT mandó tres peticiones por mensaje a otra
terminal. Resultado medido:

| Ruta | Resultado |
|---|---|
| AUDIT → PROMPTS → **Diego pega** → core | `46a65ce`: arregló las dos cosas y fue más allá |
| AUDIT → PROMPTS (solo mensaje) | sin rastro |
| AUDIT → PROMPTS (solo mensaje) | sin rastro |

Lo único que llegó a código tenía a una persona pegando en el medio. Y lo peor no es que
las otras dos se perdieran: es que **no se puede saber si se perdieron**. Un mensaje a una
sesión muerta no da error, así que "entregado y en curso" y "evaporado" se ven idénticos
desde afuera.

Agravante medido: los nombres de sesión rotan solos. En 30 horas, PROMPTS fue
`zero-prompts-ec`, después `-28`, después `-fb`. AUDIT fue `audit-29` y después
`audit-e2`, con la misma conversación detrás. La dirección **es** el nombre, así que una
petición escrita ayer no se puede reintentar hoy.

Conclusión: contar saltos era la variable equivocada. El canal no era lento, era volátil.

## La regla

> **El anillo avisa; los archivos mandan.**

Ninguna petición de trabajo existe solo como mensaje. Queda escrita primero; el mensaje,
si lo hay, es el aviso de que está escrita.

## Los tres carriles

Un hallazgo se enruta por **qué tan determinado está su arreglo**, no por a qué sección
pertenece.

### Carril 1 — El arreglo está determinado → al disco

Sé el archivo, la línea, el comando que lo prueba y qué hay que cambiar. No necesita que
nadie decida nada.

Va a `auditoria-criterio.json`, con la misma forma que `auditoria.json`. De ahí lo toma la
maquinaria que **ya existe y ya está probada**:

```
auditoria-criterio.json → planificar.py → tareas.json → tanda.py → workspace
                                ↑
                  dedup · alcance · 4 puertas · historial
```

Por qué este carril y no un mensaje: sobrevive a que muera una sesión, a que se renombre y
al reinicio de la máquina. Cuesta **cero llamadas de modelo** hasta el planificador, que
ya corre en haiku. Y hereda el dedup de `0c81b19`, que es lo que cortó la inundación de
duplicados de agosto.

`planificar.py:116` ya describe exactamente esta señal:

> *"Es la señal de mayor calidad que tiene el planificador, porque cada línea viene con un
> comando que la reproduce (…) Una tarea nacida de acá tiene criterio de terminado gratis."*

Esa es, palabra por palabra, la regla dura de AUDIT.

### Carril 2 — El arreglo es una decisión → PROMPTS

El hallazgo es real y está probado, pero el arreglo tiene alternativas con consecuencias
distintas: ¿renombrar a qué? ¿toca otras secciones? ¿en qué orden con lo que ya está
encolado?

Ahí el salto se paga solo, porque PROMPTS ve los siete workspaces y secuencia. Un ejemplo
real: la colisión de nombre de `industry` (D2 del 2026-08-29) toca `core`, y además
`motor-whatsapp` y `motor-llamadas` tienen tareas abiertas que van a leer ese campo. Eso
no lo decide un planificador solo.

**También va por acá todo lo que cambie una política de seguridad**, aunque el arreglo
parezca obvio. F1 del 2026-08-30 —que el aborto de la tanda avise antes del `return 2`—
toca una guarda que existe para que un agente autónomo no mande correos reales. Un cambio
ahí lo mira una persona.

### Carril 3 — Directo a la terminal: solo conversación en vuelo

Cuando otra terminal pregunta algo y AUDIT responde, como la verificación del 2026-08-28.
Eso es un diálogo, no repartir trabajo.

**Nunca se reparte trabajo directo a una terminal.** Ahorra un salto y pierde todo lo
demás: se salta el dedup y las cuatro puertas, no queda rastro, y la terminal arranca en
frío igual — así que ni siquiera ahorra el arranque que uno creería.

## Qué NO entra en el carril 1

El filtro es el mismo que `scripts/auditar.py` se impone a sí mismo, y por la misma razón
que explica su docstring: un modelo al que se le pide encontrar problemas siempre
encuentra alguno, y cada tarea inventada cuesta una corrida de agente y deja código que
igual hay que mantener.

Para entrar al carril 1, un hallazgo necesita las tres cosas:

1. **Un comando que lo reproduce.** Si no se puede escribir, es opinión.
2. **Gravedad alta.** `planificar.py` ya descarta lo medio: se reporta para que una
   persona lo mire, no para gastarle una corrida de agente.
3. **Un arreglo determinado.** Si hay que elegir entre alternativas, es carril 2.

El filtro es estricto a propósito. En el informe del 2026-08-30, de cinco hallazgos
abiertos **uno solo** calificaba (D1: `industry` no está en `crm._FIELDS`). Los otros
cuatro eran decisiones o datos. Que el filtro deje pasar poco es la señal de que funciona.

## Contra qué árbol corre cada comprobación

Toda verificación declara desde dónde corre. El 2026-08-29 comprobé D1 desde
`/home/diego/zeroai` (que está en `main`), donde el campo no existe todavía, y el chequeo
dio **falso "resuelto"**. El commit vivía en `core`.

```
desde /home/diego/zeroai (main):   se pierde al guardar: []          ← falso negativo
desde /home/diego/zero-core:       se pierde al guardar: ['industry']
```

Un verificador que se equivoca en esa dirección es peor que no tenerlo: firma que algo
está hecho. Los datos y el código de un worktree **no** son los de `main`.

## Estado de esto

Hecho:
- Este documento.
- AUDIT escribe `auditoria-criterio.json` con sus hallazgos altos de arreglo determinado.

Pendiente (carril 2, son cambios en `core`):
- Que `planificar.py` lea `auditoria-criterio.json` además de `auditoria.json`. Hoy el
  archivo se escribe y **nadie lo lee todavía**: hasta que ese cambio entre, el carril 1
  termina en el disco y no llega a la cola.
- Que `auditoria-criterio.json` entre al `.gitignore`, junto a `auditoria.json` en la
  línea 39. Es un dato local con el mismo trato, pero hoy aparece como archivo sin
  seguimiento en el repo principal, así que un `git add -A` distraído lo versionaría.
- Que `auditar.py` distinga `omitido` de `ok`: el check del build del dashboard devuelve
  "sin hallazgos" cuando no puede correr, y en el worktree de AUDIT no puede correr nunca.
