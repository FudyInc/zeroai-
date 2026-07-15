# Futuro / escalabilidad — qué considerar cuando haya clientes reales

Todo lo de acá es **a demanda, no ahora**: perfeccionar lo gratis sigue siendo la
prioridad ([[zero-cost-policy]]). Este archivo existe para no perder de vista qué
palancas están disponibles cuando el negocio las justifique (clientes pagando,
volumen real). Versión detallada de la sección "⏸️ Pendientes de PAGO" de
`docs/roadmap.md` (que se mantiene como resumen corto — este archivo es el contexto
completo detrás de cada ítem).

---

## 💰 Bloqueados por presupuesto (listos técnicamente, solo falta pagar)

- **Meta Ads real** — insights (gasto/leads/CPL reales de la API de Meta) y que el plan
  de Claude se **aplique** de verdad (pausar campaña, ajustar presupuesto). La cuenta de
  Meta nueva además tiene cooldown inicial — sumar ese tiempo al plan si se activa.
- **Discovery con proveedor con key** — hoy la búsqueda de leads nuevos usa
  DuckDuckGo gratis (cobertura parcial). Un proveedor pago da cobertura real y
  consistente — importante si el pipeline de prospección se vuelve el cuello de botella
  con clientes reales.
- **Envío a volumen** (email/WhatsApp) — hoy sirve para el volumen actual, pero
  deliverability a escala (que no caiga en spam) necesita un proveedor dedicado tipo SES
  o similar. Revisar cuando el volumen de envíos empiece a importar.

## 🔊 Voz y llamadas — mejoras posibles, no bloqueantes

- **ElevenLabs Professional Voice Cloning** — hoy Francisca usa clonación **instantánea**
  (1-3 min de audio). La clonación **profesional** (30+ min de audio + aprobación de
  ElevenLabs) da mejor calidad — vale la pena si la voz actual se siente robótica en
  llamadas reales con clientes.
- **Detección de tono por audio (no solo texto)** — hoy Francisca/CONCIERGE leen el
  tono del cliente por lo que DICEN (texto/transcript). Si Vapi u otra plataforma
  expone análisis de prosodia/sentimiento del audio real, sería más preciso (capta
  frustración en la VOZ aunque las palabras sean neutras) — **sin verificar todavía si
  Vapi lo ofrece en el plan actual**, investigar antes de prometerlo. Construir esto
  desde cero (pipeline propio de emoción por audio) es un frente de ingeniería grande —
  no vale la pena hasta tener varios clientes activos en llamadas.
- **Otros vendedores con voz propia** — hoy solo Francisca (llamadas) tiene voz real
  clonada. Si se suman más personas (ej. Stéfano con su propia voz), es el mismo
  proceso: alguien clona su voz en ElevenLabs, se agrega el Voice ID.

## 📱 WhatsApp — fricción de escalar a más vendedores

- **Cada vendedor nuevo necesita su propio número de WhatsApp Business verificado por
  Meta** — no es solo código: es un proceso manual (verificación de Meta, puede tener
  demoras/cooldown como con Meta Ads). Si se planea escalar a varios vendedores
  atendiendo distintos clientes en paralelo, este proceso de alta hay que empezarlo con
  antelación, no el mismo día que se necesita.

## 🖥️ Modelo local (Ollama) — límites de escala

- El modelo local activado hoy corre en un PC **sin GPU** (Ryzen 7 9700X, 16GB RAM) —
  funciona para el volumen actual, pero **no va a aguantar muchas llamadas/conversaciones
  concurrentes** a la vez. Cuando el volumen crezca, las opciones son: (a) pasar esos
  clientes a Anthropic real (pago, pero rápido y sin límite de concurrencia), o (b)
  invertir en una máquina con GPU dedicada para servir el modelo local a más escala.
  No es urgente — es la señal a vigilar: si las respuestas empiezan a demorar o
  encolarse, es momento de mirar esto.

## 🎯 Estrategia — especialización vertical (diferenciación vs. competidores tipo Nexor)

Hoy ZeroAI es horizontal (cualquier rubro). Especializarse en 1-2 verticales (ej. PyMEs
exportadoras, servicios B2B) daría calificación/mensajes mucho mejor calibrados que una
herramienta genérica — pero es prematuro sin clientes reales que validen cuál vertical
conviene. Revisar esta idea una vez que haya un patrón claro de qué tipo de cliente
convierte mejor.

## 🌐 Landing pública

`web/` sigue sin construirse a fondo (aparcado, ver memoria de la sección LANDING) —
no es un tema de pago, es simplemente que no se ha priorizado. Retomar cuando el resto
esté más maduro o cuando haya necesidad real de captar leads propios de ZeroAI ahí.

## 🏆 Prueba social

No inventar testimonios/logos de clientes falsos — se agregan a la landing/dashboard
solo cuando haya clientes reales dispuestos a aparecer.

---

## Ya NO está pendiente (activado por decisión explícita de Diego, pese a la política de cero gasto)
- **Vapi** (llamadas salientes reales) — conectado.
- **Supabase** (CRM/estado en la nube) — conectado, proyecto "zeroai".
- **Motor real vía Ollama (modelo local, gratis)** — activado en producción (ver
  `docs/GO-LIVE.md`); Anthropic de pago sigue disponible como alternativa si Ollama no
  alcanza (ver límites de escala arriba).
- **ElevenLabs** (voz de Francisca) — key cargada, Voice ID real conectado al agente de
  llamadas.
