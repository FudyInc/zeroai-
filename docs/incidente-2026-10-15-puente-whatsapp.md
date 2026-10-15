# Puente de WhatsApp caído — diagnóstico para quien lo retome

**Estado al 2026-10-15:** el agente de LosetasChile no responde. Lleva así
desde la tarde del 2026-10-14. El backend está sano; el puente no.

Esto es un traspaso entre sesiones que comparten el worktree
`/home/diego/zero-motor-whatsapp`. Trae lo ya descartado para que nadie
repita el camino.

## Síntoma

```
$ curl -s -H "Authorization: Bearer $WHATSAPP_WEB_BRIDGE_TOKEN" \
    http://127.0.0.1:8810/status
  state            connecting      # nunca llega a ready
  account          None
  error            None            # no hay error que leer
  pide QR          False           # la sesión sigue válida
```

`zero-backend.service` responde `/api/health` OK. El puente arranca, carga
Chromium, autentica, y se queda en `connecting` hasta que la guarda de
reinicio lo mata y systemd lo relanza.

## Causa raíz, con evidencia

WhatsApp Web **sí carga y sí tiene la sesión iniciada**. Medido por CDP contra
la página real del puente:

```
$ # puerto en .session/session/DevToolsActivePort, luego Runtime.evaluate
{"titulo":"(2) WhatsApp Business","store":"undefined",
 "wwebjs":"object","req":"function"}
```

- `titulo` trae el contador de no leídos → la app está viva y logueada.
- `wwebjs: object` → la inyección de whatsapp-web.js corrió.
- `req: function` → el sistema de módulos de WhatsApp responde.
- **`store: undefined`** → `window.Store` nunca se construye.

`Client.js` espera ese objeto para emitir `ready`. Sin él, `ready` no ocurre
jamás y el estado se queda en `connecting` para siempre.

Es una incompatibilidad entre **whatsapp-web.js 1.34.7** (instalada y
declarada) y la versión de WhatsApp Web que el servidor sirve hoy. El puente
no fija versión web: `webVersionCache` no aparece en `index.js`, así que carga
la que WhatsApp entregue ese día. Eso explica que funcionara a las 19:57 del
2026-10-14 y no a las 20:18 — cambió lo servido, no el código.

## Qué YA se descartó (no repetir)

| Hipótesis | Cómo se descartó |
|---|---|
| Umbral de reinicio muy corto | Era real pero secundario. Se subió de 120s a 300s configurable (`f589603`); el puente igual no llega a `ready`. Solo ocultaba el fallo tras un bucle de reinicios |
| Sesión perdida / hace falta QR | `pide QR: False` y el título muestra la cuenta logueada |
| Chromium no arranca | Arranca: PID hijo del puente, perfil correcto, sin `SingletonLock` |
| Procesos huérfanos bloqueando el perfil | No hay; el árbol de Chromium cuelga del puente actual |
| Perfil inflado (933 MB) | Es real —853 MB son caché pura, la sesión son 19 MB— pero no es la causa: la página carga bien |
| Red / WhatsApp caído | La app carga y sincroniza; lo que falla es la inyección |

## Arreglos posibles

1. **Fijar la versión de WhatsApp Web** (`webVersionCache` de tipo `remote`
   apuntando a una versión conocida compatible). Es el remedio estándar para
   este síntoma exacto y evita que vuelva a ocurrir cuando WhatsApp actualice.
   Agrega una descarga al arrancar. **Recomendado.**
2. **Actualizar whatsapp-web.js.** Cambia una dependencia del proyecto —
   requiere visto bueno de Diego (CLAUDE.md) — y no hay garantía de que la
   versión nueva ya lo resuelva.
3. **Limpiar caché de Chromium** (`Default/Cache`, `Default/Code Cache`,
   `Default/Service Worker`). Puede forzar una recarga limpia si un service
   worker viejo sirve un build incompatible. No toca `IndexedDB` ni
   `Local Storage`, así que no debería pedir QR. Barato de probar.

## Restricciones vigentes

- **No tocar `/home/diego/zeroai` a ciegas.** Es producción. Ver la memoria
  *Worktree del backend activo*. Al 2026-10-15 quedó en `main` y limpio.
- Reiniciar sin sudo: `kill -TERM $(systemctl show zero-backend -p MainPID --value)`;
  `Restart=always` lo levanta.
- Salud OK del backend **no** prueba entrega en WhatsApp. Eso solo lo confirma
  Diego en su teléfono.
- No enviar mensajes de prueba desde herramientas.

## Pendientes que NO son este incidente

- Hay un **`mcp_token` tipo JWT dentro del historial de conversaciones** en
  Supabase (7 apariciones). Conviene revocarlo. El exportador del set de
  evaluación ya lo redacta, pero el token sigue vivo en el almacén.
- `scripts/{exportar_set_evaluacion,rubrica_evaluacion,evaluar_linea_base}.py`
  y sus tres tests están **sin commitear** en este worktree: son la etapa 0 de
  la evaluación, 58 pruebas en verde. No los borres.
- La corrida de línea base quedó a medias (`docs/evaluacion/` vacío) porque la
  sesión anterior terminó antes.

---

## Actualización 2026-10-15 ~13:45 — la fijación no bastó, y por qué

Otra sesión (Codex) añadió fijación de versión web a `index.js`
(`pinnedWebVersion` desde `WHATSAPP_WEB_VERSION`) y puso
`WHATSAPP_WEB_VERSION=2.3000.1050428120` en `.env`. El puente reinició con
ella. **No resolvió:**

```
$ # CDP contra la página del puente, con la versión fijada activa
{"titulo":"(2) WhatsApp Business","store":"undefined","storeKeys":0,
 "wwebjs":"object","req":"function"}
```

El mecanismo de fijación funciona; la versión elegida no sirve.

**Por qué:** `2.3000.1050428120` se cacheó el 15-oct 01:56, o sea **ya dentro
del período roto**. El corte empezó el 14-oct alrededor de las 20:18.

Reconstrucción por marca de tiempo de `.wwebjs_cache/`:

| Versión | Cacheada | Evidencia |
|---|---|---|
| `2.3000.1050357358` | 14-oct 18:03 | **el puente estuvo `ready` a las 19:57 con esta** |
| `2.3000.1050372399` | 14-oct 21:12 | posterior al corte |
| `2.3000.1050428120` | 15-oct 01:56 | la fijada hoy — no funciona |
| `2.3000.1050469598` | 15-oct 13:32 | la más nueva |

**Candidato con evidencia:** fijar `WHATSAPP_WEB_VERSION=2.3000.1050357358`,
la última versión bajo la cual el puente alcanzó `ready` de forma confirmada
(estado `ready`, cuenta `56964537891`). El archivo ya está en
`.wwebjs_cache/`, así que con `strict: true` cargará sin red.

Si esa tampoco construye `Store`, la hipótesis «cambió el WhatsApp Web
servido» queda descartada y el siguiente sospechoso es el perfil de Chromium
(service worker viejo sirviendo un build incompatible pese a la fijación):
borrar `Default/Cache`, `Default/Code Cache` y `Default/Service Worker`,
**nunca** `IndexedDB` ni `Local Storage`.

**Cuidado con la concurrencia:** al 2026-10-15 13:37 había dos sesiones
tocando esto. `.env` y el servicio son recursos compartidos; dos reinicios
simultáneos se pisan y confunden el diagnóstico. Que lo conduzca una sola.

## Actualización 2026-10-15 ~14:20 — fijar la versión NO es el arreglo

Probado y descartado. Se fijó `WHATSAPP_WEB_VERSION=2.3000.1050357358` —la
última bajo la cual el puente llegó a `ready` de forma confirmada— y se
reinició el backend para que la variable llegara al puente:

```
$ tr '\0' '\n' < /proc/<pid>/environ | grep WHATSAPP_WEB_VERSION
WHATSAPP_WEB_VERSION=2.3000.1050357358        # el puente SÍ la tomó
$ # CDP sobre la página, 3 minutos después
{"t":"(2) WhatsApp Business","store":"undefined","k":0,"w":"object"}
```

**Dos versiones distintas, el mismo fallo.** La hipótesis «cambió el WhatsApp
Web servido» queda descartada: no es la versión del HTML.

**Por qué la fijación no alcanzaba, en retrospectiva:** `webVersionCache` fija
el `index.html` que se carga, pero los *bundles* de JavaScript de WhatsApp Web
los resuelve el navegador — y hay un **service worker registrado** para
`web.whatsapp.com` con 27 MB en disco. Un service worker viejo sirve sus
propios bundles cacheados sin importar qué HTML se fije. Eso explica que dos
HTML distintos den exactamente el mismo resultado.

**Siguiente sospechoso, ahora el principal:** el perfil de Chromium.
Borrar `Default/Service Worker`, `Default/Cache` y `Default/Code Cache`
(≈880 MB, todo regenerable). **Nunca** `Default/IndexedDB` ni
`Default/Local Storage` (19 MB juntos): ahí vive el vínculo con el teléfono y
borrarlos obliga a escanear QR de nuevo.

Nada de lo borrado contiene mensajes: las conversaciones viven en los
servidores de WhatsApp y en el teléfono, el historial del agente en Supabase,
y los eventos entrantes en `whatsapp-web-events.sqlite3`.

**Nota de concurrencia:** esta prueba sobrescribió el valor que Codex había
puesto (`2.3000.1050428120`). Respaldo del `.env` previo en
`/home/diego/zero-backups/env-antes-pin-141551.bak`. Ninguno de los dos
valores funciona, así que no hay nada que restaurar salvo que se quiera el
estado exacto anterior.

## RESUELTO 2026-10-15 ~14:25 — era el perfil de Chromium

El puente volvió a `ready` con la cuenta `56964537891`, **sin pedir QR**.

Lo que lo arregló: apartar tres carpetas del perfil de Chromium. Se
**renombraron**, no se borraron — un renombre es instantáneo aunque pesen
cientos de MB, no compite con el Chromium en marcha, y se deshace con otro
renombre:

```
Cache           553 MB  ->  Cache.old-142123
Code Cache      334 MB  ->  Code Cache.old-142123
Service Worker   33 MB  ->  Service Worker.old-142123
```

`IndexedDB`, `Local Storage` y `Session Storage` no se tocaron, y además se
copiaron a `/home/diego/zero-backups/wa-session-vinculo-142123/` (22 MB). Por
eso el vínculo con el teléfono sobrevivió.

**Confirmación de la causa:** el puente solo emite `ready` cuando
whatsapp-web.js logró construir `window.Store`. Con el perfil viejo, `Store`
quedaba `undefined` bajo **dos versiones web distintas**; con el perfil limpio
y la misma librería 1.34.7, llega a `ready` en 6 segundos. El service worker
cacheado servía bundles incompatibles pese a la versión fijada.

**Conclusión práctica:** ante `connecting` perpetuo con la sesión válida y sin
QR, el primer sospechoso es el perfil de Chromium, no la versión de WhatsApp
Web ni la librería.

### Qué queda por limpiar o revisar

- Las tres carpetas `*.old-142123` ocupan 920 MB y se pueden borrar cuando el
  puente lleve un rato estable. No antes: son la vuelta atrás.
- `WHATSAPP_WEB_VERSION` quedó en `2.3000.1050357358`. **Ya no se sabe si la
  fijación aporta algo**, porque lo que arregló fue el perfil. Conviene
  decidir si se mantiene fija (protege de un cambio de WhatsApp, pero congela
  una versión que envejece) o se suelta.
- El estado reporta un error no fatal:
  `Recuperación entrante: Attempted to use detached Frame`. Es
  `recoverRecentMessages` corriendo a los 5 s del arranque mientras el frame
  aún se reemplazaba. No impide operar —el estado es `ready`— pero conviene
  que esa recuperación espere a que el frame esté estable.
