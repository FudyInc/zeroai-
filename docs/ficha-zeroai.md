# Ficha de ZeroAI — base de conocimiento del agente de WhatsApp

Esta es la **fuente canónica y versionada** de la ficha que Fernanda usa para vender
los servicios de ZeroAI por WhatsApp. Se carga en `memory.set_client_knowledge`
(cliente `zeroai`) y viaja en `data.knowledge` hacia CONCIERGE.

- **Editar acá, no solo en el dashboard.** El dashboard escribe en `state.json`, que es
  local y gitignorado: si se pierde, esto la reconstruye.
- **Límite duro: 4000 caracteres.** `orchestrator.reply_to_inbound` la corta ahí
  (`[:4000]`). Lo que se pase de esa marca no llega al modelo.
- **Sin montos.** Los precios de los planes NO van acá a propósito: el prompt de
  CONCIERGE prohíbe que el agente escriba cifras (los presupuestos los calcula
  `quotes.py`, determinista). Una cifra en la ficha es una invitación a romper esa regla.

---

<!-- INICIO FICHA (esto es lo que se carga tal cual) -->

ZeroAI es una empresa chilena de IA aplicada a ventas y marketing B2B. No vendemos
software para que el cliente lo use: operamos los agentes nosotros y el cliente recibe
el resultado.

QUÉ HACEMOS (4 líneas de servicio)

1. Generación de leads B2B calificados. Nuestros agentes descubren empresas que
   encajan con el perfil de cliente ideal, las califican con un puntaje, validan los
   datos de contacto y hacen el primer contacto. El cliente recibe leads listos para
   contactar, no una lista fría comprada.

2. Agentes de WhatsApp. Ponemos un agente en el WhatsApp de la empresa que responde en
   segundos, 24/7, con el catálogo, el tono y las políticas de esa empresa. Atiende
   ventas (capta, califica, agenda) y servicio (resuelve dudas, escala a una persona
   cuando corresponde). Deja de perderse ventas por no contestar a tiempo.

3. Automatización de procesos. Tareas comerciales repetitivas que hoy consumen a un
   equipo: seguimiento de leads, actualización del CRM, reportes, secuencias de
   contacto. El agente las ejecuta solo y avisa cuando algo necesita a una persona.

4. Agentic marketing. Campañas operadas por agentes de punta a punta, conectadas al
   mismo pipeline de leads, para que el gasto en publicidad se mida en leads
   calificados y no en impresiones.

CÓMO FUNCIONA

El pipeline es: descubrir, calificar, validar, contactar, hacer seguimiento y
proyectar. Cada lead queda registrado en un CRM con su etapa y su historial, así el
cliente ve en qué va cada oportunidad. Hay un tablero donde revisa todo.

CÓMO COBRAMOS

Plan mensual según el volumen de leads que necesite la empresa, con distintos niveles
de calificación y canales según el plan. En los planes más altos se suman llamadas y
LinkedIn además de correo y WhatsApp. Hay un plan a medida para empresas grandes.
Nunca des cifras por WhatsApp: si preguntan precio, ofrece armar una propuesta a
medida en una llamada corta de 10 minutos.

A QUIÉN LE SERVIMOS

Empresas B2B en Chile que venden a otras empresas y que hoy prospectan a mano o no
prospectan. Hablamos con el dueño, el gerente comercial o el gerente de marketing.

QUÉ NOS DIFERENCIA

- El cliente recibe leads calificados, no una lista comprada.
- Los agentes operan solos y de punta a punta; no es una herramienta más que alguien
  tiene que aprender a usar.
- Transparencia: si a un agente le preguntan si es una IA, lo dice. Eso protege el
  número de WhatsApp de la empresa (Meta suspende cuentas que se hacen pasar por
  humanas) y protege la marca.
- Se adapta al negocio de cada cliente: cada empresa carga su ficha, su catálogo y su
  perfil de cliente ideal, y los agentes trabajan con eso.

CÓMO LO DEMOSTRAMOS

La mejor demo es esta misma conversación: quien escribe está hablando con un agente de
ZeroAI. Si quiere ver más, se le muestra el tablero con el pipeline real.

OFERTA DE ENTRADA

A quien todavía no nos conoce le ofrecemos 10 leads calificados de prueba, gratis y
para su rubro: empresa, decisor, contacto verificado y el primer mensaje ya escrito.
Sin compromiso y sin tarjeta — así ve la calidad antes de decidir nada. Es la forma
más rápida de pasar de un correo frío a una conversación.

LO QUE NO HACEMOS

No vendemos leads B2C ni bases de datos. No garantizamos ventas cerradas: entregamos
leads calificados y el contacto hecho. No hacemos desarrollo de software a medida
fuera de estas cuatro líneas.

<!-- FIN FICHA -->
