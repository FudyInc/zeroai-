# Entorno de trabajo en Cursor (reemplazo de Conductor)

Conductor era una app **solo para Mac**. Lo que hacía por debajo se replica con
`git worktree` + los terminales de Cursor, sin instalar nada extra y sin costo.

En el PC Linux (WSL2) el home es `/home/<usuario>` directo — **no hay carpeta
`Desktop`**. El script deja las carpetas ahí, hermanas del repo clonado.

## Montarlo (una sola vez)

```bash
git clone https://github.com/FudyInc/zeroai-.git zeroai
cd zeroai
bash scripts/setup-workspaces.sh
```

Eso deja una carpeta por sección, hermanas del repo, cada una en su propia rama:

```
/home/<usuario>/
├── zeroai/                  ← main (integración)
├── zero-core/               ← rama core
├── zero-dashboard/          ← rama dashboard
├── zero-motor-whatsapp/
├── zero-motor-llamadas/
├── zero-landing/
├── zero-prompts/
└── zeroai.code-workspace    ← ábrelo en Cursor
```

Al abrir `zeroai.code-workspace`, Cursor muestra las 7 carpetas en una sola
ventana, cada una con su rama, sin que se mezclen entre sí.

**Cómo abrirlo en Cursor (WSL):** con la ventana de Cursor ya conectada a WSL
(`Remote-WSL`), `Ctrl+K Ctrl+O` → **"Open Workspace from File..."** → navegar a
`/home/<usuario>/zeroai.code-workspace`. Si Cursor abre por fuera de WSL (en
Windows), primero conéctate a la distro con la paleta de comandos
(`Ctrl+Shift+P` → "Connect to WSL").

## Trabajar

Una terminal por sección (`Ctrl+Shift+ñ` abre una nueva en Cursor):

```bash
cd /home/<usuario>/zero-core && claude
```

Ese es el equivalente exacto a un terminal de Conductor: un agente por sección,
aislado en su worktree. Abre tantas pestañas como secciones necesites.

## Por qué worktrees y no clones separados

Todos comparten el mismo `.git`: un `git fetch` sirve para todas, no se duplica
el historial (100+ MB por copia) y las ramas no se pisan — git impide tener la
misma rama abierta en dos carpetas a la vez.

## Reglas que no cambian

Las fronteras entre secciones siguen siendo las mismas que en Conductor (ver
`CLAUDE.md`): CORE toca `api.py` y `zero/*.py` no-agente; DASHBOARD solo
`frontend/`; MOTOR solo su propio agente. El aislamiento ahora lo da el
worktree, no la app.

## Flujo de integración

Igual que siempre: trabajar en la rama de la sección → tests en verde → push a
su rama → fusionar a `main` → desplegar.

```bash
python3 -m unittest discover -s tests -t .   # antes de cualquier push
```

## Si extrañas la vista de conjunto

`Claude Squad` (open source, `npx`, gratis) da un panel tipo kanban sobre este
mismo esquema de worktrees. No hace falta para trabajar — pruébalo solo si
sientes que te falta ver todos los agentes a la vez.
