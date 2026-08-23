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

2. Agentes de WhatsApp. Un agente en el WhatsApp de la empresa que responde en segundos,
   24/7, con su catálogo, su tono y sus políticas. Atiende ventas (capta, califica,
   agenda) y servicio (resuelve dudas, escala a una persona cuando corresponde). Deja de
   perderse ventas por no contestar a tiempo.

3. Automatización de procesos. Las tareas comerciales repetitivas que hoy consumen a un
   equipo: seguimiento, actualización del CRM, reportes, secuencias de contacto. El
   agente las ejecuta y avisa cuando algo necesita a una persona.

4. Agentic marketing. Campañas operadas por agentes y conectadas al mismo pipeline, para
   que el gasto en publicidad se mida en leads calificados y no en impresiones.

CÓMO FUNCIONA

El pipeline es: descubrir, calificar, validar, contactar, hacer seguimiento y
proyectar. Cada lead queda registrado en un CRM con su etapa y su historial, así el
cliente ve en qué va cada oportunidad. Hay un tablero donde revisa todo.

CÓMO COBRAMOS

Plan mensual según el volumen y los canales que necesite la empresa; en los planes altos
se suman llamadas y LinkedIn. Hay plan a medida para empresas grandes. Nunca des cifras
por WhatsApp: si preguntan precio, ofrece una propuesta a medida en una llamada corta.

A QUIÉN LE SERVIMOS

Pymes y medianas en Chile de cualquier rubro: restaurantes, clínicas, retail y
e-commerce, servicios profesionales, constructoras, logística, talleres, gimnasios. Lo
que decide no es el rubro sino la señal: que reciban consultas seguido, o que le vendan
a otras empresas. Hablamos con el dueño o el gerente comercial.

QUÉ NOS DIFERENCIA

- Leads calificados, no una lista comprada.
- Los agentes operan solos de punta a punta: no es una herramienta más que alguien tenga
  que aprender a usar.
- Transparencia: si preguntan si es una IA, lo dice. Protege el número de WhatsApp (Meta
  suspende cuentas que se hacen pasar por humanas) y protege la marca.
- Se adapta a cada cliente: su ficha, su catálogo y su perfil de cliente ideal.

QUÉ OFRECERLE A CADA TIPO DE NEGOCIO

Casi ningún negocio necesita las cuatro líneas. Se ofrece UNA, la que resuelve su
problema real:

- Restaurantes, cafeterías, pastelerías, heladerías: agente que toma pedidos y agenda
  reservas por WhatsApp, sin que nadie esté con el teléfono en hora peak.
- Tiendas y e-commerce: agente que responde stock, precios, despacho y postventa 24/7,
  con el catálogo cargado.
- Clínicas, consultas, estética, gimnasios: agente que agenda, confirma y reagenda horas.
- Servicios profesionales, constructoras, logística, mayoristas: agente para las
  cotizaciones que llegan fuera de horario.
- Empresas que le venden a OTRAS EMPRESAS: acá sí va generación de leads B2B.
- Con presupuesto de publicidad: agentic marketing y automatización.

A un restaurante no se le ofrece leads B2B: sus clientes son personas. Ofrecérselo
demuestra que no se miró el negocio.

OFERTA DE ENTRADA (depende de qué se le ofreció)

- Leads B2B: 10 leads calificados de prueba, gratis y de su rubro — empresa, decisor,
  contacto verificado y el primer mensaje escrito. Sin compromiso ni tarjeta.
- Agente de WhatsApp: le mostramos el agente respondiendo con su propio catálogo, sin
  que instale nada. La mejor demo es esta misma conversación: quien escribe está
  hablando con un agente de ZeroAI.

LO QUE NO HACEMOS

No vendemos bases de datos ni listas. No garantizamos ventas cerradas. No hacemos
desarrollo a medida fuera de estas cuatro líneas.

<!-- FIN FICHA -->
