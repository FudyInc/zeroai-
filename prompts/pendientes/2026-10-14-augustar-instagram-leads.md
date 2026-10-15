# Pedido: recolección de leads de Instagram para Augustar Seguros

**De:** terminal dashboard (zero-dashboard-e8) · **Para:** MOTOR INSTAGRAM · **Fecha:** 2026-10-14
**Pedido por:** Diego

## Qué se quiere

Stefano (rol `operador`, acotado al cliente `Augustar Seguros`) necesita la pestaña
**Agentes** en el dashboard, con **Instagram priorizado**, para recolectar leads de
Instagram y verlos en su Pipeline.

Flujo de negocio (de la spec): anuncio de Instagram → formulario instantáneo de Meta que
pregunta **rango de renta** (opción múltiple) y **teléfono** → se importa al CRM de
`Augustar Seguros` en etapa `new` con origen Instagram Ads → Stefano llama y mueve la
etapa a mano.

## Estado verificado hoy (con comandos)

- **Producción.** Vercel (`zeroai-six.vercel.app`) publica desde `origin/main`, que ya
  está en `ab759ec` (rol operador). En main, la tarjeta de Instagram de `Agentes.jsx` dice
  "No viable (ToS)" y `POST /api/campaigns/sync-leads` responde 501. Se comprueba con
  `git show origin/main:api.py | grep -n "sync-leads" -A12`.
- **Implementación existente, sin commitear.** La importación ya está escrita en
  `/home/diego/zero-dashboard` (rama `dashboard`, base `f802c1b`, 29 commits detrás de
  main). Las piezas de Instagram son estas:
  - `zero/metaads.py` → `lead_ads()` con el campo `income_range` (renta / ingreso /
    sueldo, o la única pregunta personalizada que haya).
  - `zero/crm.py` y `zero/crm_supabase.py` → persisten `income_range`.
  - `supabase_schema.sql` → la columna `income_range`. **No está aplicada en la base de
    producción.**
  - `api.py` → implementación real de `sync-leads`, más `lead_form_ids` y `lead_platform`
    en `POST /api/marketing`.
  - `tests/test_metaads.py` → los tests.
  - `LeadModal.jsx` y `Pipeline.jsx` → muestran la renta.
  - `Campanas.jsx` → botón "Importar formularios" y campos de plataforma e IDs de
    formulario.

  Puedes verlo con `git -C /home/diego/zero-dashboard diff -- api.py zero/ tests/test_metaads.py`.
  Spec: `docs/superpowers/specs/2026-10-14-augustar-instagram-leads-design.md`.
  Plan: `docs/superpowers/plans/2026-10-14-augustar-instagram-leads.md` (ambos en ese
  mismo checkout, sin commitear).
- **Ojo.** En ese checkout hay más trabajo sin commitear que **no** es de este pedido:
  rediseño de WhatsApp, Config, Agentes e `index.css`. No lo arrastres.
- **Cliente.** `Augustar Seguros` existe en Supabase (STARTER, sin leads). Hasta hoy no
  tiene token de Meta, ni cuenta publicitaria, ni IDs de formulario.

## Qué hay que hacer

1. Portar a una rama sobre `origin/main` **solo** la importación de Instagram Lead Ads
   (backend, CRM, schema, tests, y mostrar la renta en la ficha y el Pipeline).
2. **Operador.** Agregar `/agentes` a `PAGE_ROLES` para `operador` (`frontend/src/lib/roles.js`).
   Para ese rol, Agentes muestra **solo Instagram**, primero, con su estado (formulario
   conectado o no) y un botón "Importar leads de Instagram" que deja los leads en su
   Pipeline. WhatsApp, Email y Llamadas quedan ocultos para él.
3. **Backend.** Abrirle al operador solo lo necesario en `_ROLE_ALLOWED["operador"]`:
   `POST /api/campaigns/sync-leads` y la lectura del estado. Todo acotado con
   `_require_client` (cliente ajeno = 404, igual que el resto). Las credenciales (token
   de Meta) siguen siendo **solo de admin**.

## Decisiones abiertas (preguntarle a Diego)

- ¿Stefano solo importa, o también puede pegar los IDs de formulario de su negocio?
  Recomendación: solo importar.
- ¿Quién aplica en producción el `ALTER TABLE ... ADD COLUMN IF NOT EXISTS income_range`
  de Supabase?

## Ampliación (Diego, 2026-10-14, mismo día): vincular la cuenta de Instagram

Lo de arriba (importar formularios) es la **fase 1**. La intención de fondo es más amplia:

> Que Stefano pueda **vincular su cuenta de Instagram** al dashboard, **gestionar ahí
> todo**, y tener **agentes de IA que lo apoyen respondiendo**. Darle la mayor cantidad
> posible de herramientas.

Por eso, la **fase 2** es Instagram como canal conversacional, por la API oficial de
Meta. Es la vía viable; el scraping o los bots no oficiales quedan fuera porque violan
los ToS y arriesgan baneo.

- **Vincular la cuenta.** Debe ser una cuenta de Instagram profesional (empresa o
  creador). Se vincula con OAuth de Meta (Instagram API con login de Instagram, o vía
  Página de Facebook) y el token queda guardado por cliente, igual que el de Meta Ads
  (`client_integrations`, con hash del nombre del cliente). El token nunca va en JSON.
- **Bandeja de DMs en el dashboard.** Mensajes entrantes por webhook
  (`/api/webhooks/...`), respuesta manual de Stefano y **respuesta asistida o automática
  del agente de IA**. Para eso, reutilizar el cerebro y el flujo que ya usa WhatsApp
  (persona, ficha del negocio, aprobación); no inventar uno nuevo.
- **Comentarios.** Leer los comentarios de las publicaciones y anuncios, y que el agente
  sugiera respuestas o las envíe, incluida la respuesta privada a un comentario. Un
  comentario que muestra interés se convierte en lead del CRM.
- **Leads.** Cada conversación con interés queda como lead de `Augustar Seguros`,
  enlazada a su hilo, con el rango de renta si lo da.

### Límites reales de la plataforma (decirlos en la UI, no taparlos)

- **No hay DMs en frío.** Solo se puede responder a quien escribió primero, y dentro de
  la ventana de 24 h. Fuera de esa ventana, solo vale la etiqueta `HUMAN_AGENT` (hasta
  7 días, y la respuesta tiene que escribirla un humano).
- **Permisos de la app.** Hacen falta `instagram_manage_messages` e
  `instagram_manage_comments` (o sus equivalentes con login de Instagram). Para cuentas
  con rol en la app de Meta basta el acceso estándar. Para atender clientes que no
  tienen ese rol se necesita App Review. Verificar cuál aplica a la app de ZeroAI.
- **Webhook público.** Los webhooks exigen una URL HTTPS pública. Revisar cómo recibe hoy
  el backend local los webhooks de WhatsApp/Meta y usar la misma vía.
- **Sin modo de prueba disfrazado.** Sin la cuenta vinculada, la pantalla muestra vacío
  con el motivo (CLAUDE.md, principio 1).

### Orden sugerido

1. Fase 1: importación de formularios (lo de arriba). Es lo más corto y ya está escrito.
2. Fase 2a: vincular la cuenta y la bandeja de DMs con respuesta manual.
3. Fase 2b: el agente de IA responde DMs, primero con aprobación humana y después
   automático si Diego lo habilita.
4. Fase 2c: comentarios y su conversión a lead.

Cada fase se entrega y verifica por separado. **Antes de la 2a**, levantar con Diego qué
hay ya creado en Meta: app, permisos, página, y si la cuenta de Augustar es profesional.

## Restricciones

- Solo stdlib en el núcleo. Nada de mock en producción (CLAUDE.md, principio 1).
- Mantener el aislamiento por cliente del commit `ab759ec`.
- No crear anuncios, formularios ni webhooks en Meta; la importación sigue siendo manual.
- Tests en verde y `vite build` OK antes de pedir el push a main. El push lo confirma Diego.
