# Prompt de PROMPTS a CORE — un check omitido deja de parecer un check aprobado

Origen: pedido 1 de `prompts/pendientes/2026-09-07-de-audit.md`. Verificado contra
`origin/main` (1449e75) el 2026-09-07.

---

[TARGET: ⚙️ CORE]
Si tu sección no es CORE, detente y dilo.

ANTES DE EMPEZAR
  git fetch origin && git merge origin/main
  git status --porcelain   → limpio

OBJETIVO
Que el informe de auditoría distinga "este check no se pudo correr" de "este check pasó".
Hoy son indistinguibles, y por eso la auditoría diaria lleva desde el 2026-08-29
cerrando "sin hallazgos" con 7 de 8 checks.

CONTEXTO — el fallo está medido
`scripts/auditar.py:249`, en `build_del_dashboard()`:

    if not (REPO / "frontend" / "node_modules").is_dir():
        return []          # sin dependencias no se puede afirmar nada, ni bueno ni malo

El comentario es honesto, pero el valor que devuelve no: quien lo recibe no puede
distinguir ese `[]` del `[]` de un build verde. En el worktree de AUDIT nunca hay
`node_modules`, así que su auditoría vale 7 de 8 checks todos los días y firma igual.

Es el mismo defecto que ya costó ocho días de parálisis invisible, en su tercera
aparición: una señal que afirma con confianza algo que no midió. Las dos anteriores
fueron el aviso que no salía con la tanda muerta (904b787) y el aviso del sync que
llamaba "sin subir" a una rama que sí estaba en su remoto.

ESTO NO ES UN CAMBIO DE UNA LÍNEA — `auditoria.json` TIENE TRES CONSUMIDORES
  scripts/commitear-auditoria.sh   `normalizar()` compara el informe del día contra el
                                   guardado, quitando `cuando` y `segundos`.
  scripts/planificar.py            `hallazgos_de_la_auditoria()` toma solo gravedad alta.
  api.py  /api/ciclo/salud         sirve los informes archivados al dashboard.
Y hay informes YA ARCHIVADOS en la rama `audit/diaria` que no van a tener el campo nuevo.

La forma actual del informe (auditar.py:283-285):
    {"cuando": float,
     "checks": [{"check": str, "hallazgos": int, "segundos": float}],
     "hallazgos": [{"check","gravedad","detalle","evidencia","extra"}]}

DECISIONES YA TOMADAS

A. UN CHECK OMITIDO NO ES UN HALLAZGO, PERO SÍ ES VISIBLE.
   No inventes un hallazgo de gravedad alta por no poder correr: eso gastaría corridas de
   agente sobre algo que no está roto. Lo que se agrega es ESTADO al ítem del check:
   corrió y pasó / corrió y encontró / no se pudo correr, esta última con un motivo
   legible ("sin frontend/node_modules"). Que el conteo `hallazgos` de un check omitido
   sea 0 es correcto; lo que hoy falta es poder saber que ese 0 no significa nada.

B. LA OMISIÓN LA DECLARA EL CHECK, NO EL RUNNER.
   Hoy todas las funciones de CHECKS devuelven una lista. Dales una forma de decir "no
   pude" que el runner traduzca a estado — un sentinel o una excepción propia del módulo,
   tú eliges cuál queda más limpia. Lo que NO quiero es que el runner adivine por fuera
   (p.ej. mirando node_modules él mismo): el que sabe por qué no pudo correr es el check.

C. BARRE TODOS LOS CHECKS, NO SOLO EL BUILD.
   `build_del_dashboard` es el que está medido, pero revisa los ocho de `CHECKS`
   (auditar.py:258+) y aplica el mismo criterio donde corresponda: un timeout de `_corre`
   (devuelve 124), un archivo que no existe, una herramienta ausente. Cualquier camino que
   hoy devuelva `[]` sin haber medido nada entra. Enumera en el reporte cuáles cambiaste
   y cuáles revisaste y dejaste igual.

D. COMPATIBILIDAD HACIA ATRÁS, OBLIGATORIA.
   Los informes ya archivados en `audit/diaria` no tienen el campo. Los tres consumidores
   deben seguir funcionando con esos informes viejos: campo ausente = comportamiento de
   hoy, nunca un crash ni un "omitido" falso. Verifícalo contra un informe real de la
   rama, no contra uno que fabriques.

E. LOS TRES CONSUMIDORES, REVISADOS UNO POR UNO.
   · commitear-auditoria.sh: el campo nuevo entra en la comparación normalizada. Que un
     check pase de "omitido" a "ok" ES un cambio de salud y debe generar commit — pero
     revisa que `normalizar()` no se rompa y que no aparezca ruido nuevo por día.
   · planificar.py: sigue tomando solo hallazgos de gravedad alta. Un check omitido no
     encola trabajo. Si te parece que debería avisar de otra forma, dilo en el reporte y
     no lo hagas: es otra decisión.
   · api.py /api/ciclo/salud: el dashboard tiene que poder pintar un check omitido
     distinto de uno en verde. Tú entregas el dato; la vista es de DASHBOARD y no la
     tocas. Di en el reporte qué campo tiene que leer.

ALCANCE
  scripts/auditar.py
  scripts/commitear-auditoria.sh   (solo lo necesario para D y E)
  api.py                           (solo si /api/ciclo/salud necesita pasar el campo)
  tests/test_auditar.py            (ya existe; extiéndelo)

NO TOCAR
  frontend/**  ·  zero/agents/**  ·  scripts/tanda.py  ·  scripts/dia.sh
  tareas.json · crm.json · state.json · auditoria*.json (tu código los lee; tú no los editas)
  la rama audit/diaria — ni checkout, ni escritura
  Sin dependencias nuevas: stdlib.

ACEPTACIÓN — verificable corriendo
  1. python3 -m unittest discover -s tests -t .   → verde (hoy 975 tests OK)
  2. LA PRUEBA QUE IMPORTA, con el fallo real:
       mv frontend/node_modules /tmp/nm-guardado
       python3 scripts/auditar.py ; echo "exit=$?"
       python3 -c "import json; d=json.load(open('auditoria.json')); print([c for c in d['checks'] if c['check']=='build del dashboard'])"
       mv /tmp/nm-guardado frontend/node_modules
     El check del build tiene que quedar marcado como NO CORRIDO, con su motivo. Hoy
     queda idéntico a un build verde: ese es el defecto.
  3. Con node_modules en su sitio, corre de nuevo → el mismo check queda como corrido y
     en verde. Los dos informes tienen que verse distintos.
  4. Compatibilidad: toma un informe viejo real de la rama y pásalo por los consumidores.
       git show audit/diaria:docs/auditoria/2026-09-04.json > /tmp/viejo.json
     Comprueba que `normalizar()` lo procesa y que /api/ciclo/salud lo sirve sin romperse.
  5. curl -s "localhost:8000/api/ciclo/salud?dias=7" | head -30  → salida real en el reporte.
  6. bash scripts/commitear-auditoria.sh dos veces seguidas → la segunda dice "sin cambios"
     y no crea un commit nuevo (la garantía de 4dfe3e5 sigue en pie).

REPORTE
Qué cambiaste, qué checks pasaron a poder declararse omitidos y cuáles revisaste y
dejaste igual, y QUÉ CAMPO tiene que leer el dashboard para pintar un check omitido
distinto de uno verde — eso es el handoff. Aparte, lo que encuentres fuera de tu sección:
repórtalo, no lo arregles.
