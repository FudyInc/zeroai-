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
- **Latencia de voz (2026-07-20)**: `zero/voice.py` cambió de `eleven_multilingual_v2`
  a `eleven_flash_v2_5` (~75-150ms vs. varios segundos) — verificado que soporta
  español, el acento sigue viniendo de la voz clonada, no del modelo. Falta
  replicar el mismo cambio de modelo en el Assistant de Vapi (panel, no código).
- **Clonación de voz local/open-source (evaluado y descartado por ahora,
  2026-07-20)**: existen modelos reales (OpenVoice, Pocket TTS, LuxTTS, etc.),
  pero el PC de producción **no tiene GPU** (Ryzen 7 9700X) — a diferencia del
  LLM de texto, la clonación de voz en tiempo real generalmente necesita GPU
  para ser rápida; correrla en CPU podría salir más lenta que ElevenLabs por la
  nube, no más rápida. Revisar solo si en algún momento se compra/consigue una
  GPU, y solo si el flash de ElevenLabs no alcanza.

## 📱 WhatsApp — fricción de escalar a más vendedores

- **Cada vendedor nuevo necesita su propio número de WhatsApp Business verificado por
  Meta** — no es solo código: es un proceso manual (verificación de Meta, puede tener
  demoras/cooldown como con Meta Ads). Si se planea escalar a varios vendedores
  atendiendo distintos clientes en paralelo, este proceso de alta hay que empezarlo con
  antelación, no el mismo día que se necesita.

## 📸 Instagram — canal nuevo, viable SOLO para mensajes entrantes (verificado 2026-07-15)

Investigado contra las políticas reales de Meta (no asumido): **DMs en frío (contactar
gente que nunca escribió) siguen prohibidos sin excepción** — sin API que lo permita,
riesgo real de restricción de cuenta (7 días la primera vez, 30 días la segunda). Por
eso `Agentes.jsx` lo marca "No viable" hoy — y para DMs en frío, sigue siendo correcto.

**Lo que SÍ es viable y oficial:** responder DMs que el lead ya envió (o respuestas a
comentarios/historias), vía la **API de Mensajería de Instagram** — misma familia de
API que WhatsApp Business, mismas reglas (ventana de 24h, límite de 200 DMs
automáticos/hora).

**Bloqueante — paso manual de Diego, no código:**
1. Cuenta de Instagram **Business/Creator vinculada a una Página de Facebook**.
2. Meta debe **aprobar el permiso de Mensajería de Instagram** para la app (revisión
   de Meta, no instantánea — mismo tipo de espera que la plantilla de WhatsApp).

Recién con eso aprobado tiene sentido un prompt de código (nuevo `InstagramSender` en
`zero/channels.py`, webhook entrante, adaptar CONCIERGE al canal) — construirlo antes
sería trabajo sin nada real contra qué probarlo.

## 🖥️ Modelo local (Ollama) — límites de escala

- El modelo local activado hoy corre en un PC **sin GPU** (Ryzen 7 9700X, 16GB RAM) —
  funciona para el volumen actual, pero **no va a aguantar muchas llamadas/conversaciones
  concurrentes** a la vez. Cuando el volumen crezca, las opciones son: (a) pasar esos
  clientes a Anthropic real (pago, pero rápido y sin límite de concurrencia), o (b)
  invertir en una máquina con GPU dedicada para servir el modelo local a más escala.
  No es urgente — es la señal a vigilar: si las respuestas empiezan a demorar o
  encolarse, es momento de mirar esto.

## 🎯 Estrategia — diferenciación vs. competidores

Ver **[docs/research/mercado-competencia.md](research/mercado-competencia.md)**
(investigación real, con precios y fuentes, de Lead Fishers, B2B Rocket, AiSDR,
Adstrategy, Clay, Smartlead). Hallazgo clave de ese documento: hay un hueco de precio
entre las agencias tradicionales chilenas/LATAM (US$500–1,500/mes, trabajo manual) y
las plataformas de agentes IA (US$2,450–4,199/mes, EE.UU./global) — **ningún
competidor observado combina agentes IA + precio de agencia regional + foco
Chile/LATAM + gate de calificación estricto**. Es el espacio en blanco a apuntar.

Especialización vertical (1-2 rubros, ej. PyMEs exportadoras) daría calificación/
mensajes mejor calibrados que una herramienta horizontal — pero es prematuro sin
clientes reales que validen cuál vertical conviene. Revisar una vez que haya un
patrón claro de qué tipo de cliente convierte mejor.

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
