# Inteligencia de mercado — competencia lead-gen B2B

Documento vivo de investigación externa sobre agencias/empresas que hacen
generación de leads B2B (foco LATAM/Chile), para nutrir decisiones de negocio
de ZERO. No es un feature del producto — es un archivo de observación pasiva,
actualizado por ciclos de `/loop`.

Desde el 2026-07-06 cada hallazgo nuevo incluye una **Importancia: N/10**
(qué tan relevante es para las decisiones de negocio de ZERO específicamente,
no qué tan grande es la empresa). Entradas anteriores a esa fecha no la tienen
retroactivamente — no vale la pena reescribir hallazgos ya cerrados.

**Última revisión:** 2026-07-06

---

## Empresas observadas

### Lead Fishers (LATAM)
- **Qué hace:** agencia de lead generation que se posiciona como "#1 de LATAM".
  Combina prospección en LinkedIn + cold email para generar leads calificados;
  incluye coordinación de reuniones (no solo entrega el contacto).
- **Posicionamiento:** verticalizado por industria (tecnología, SaaS, agencias
  de marketing/desarrollo/software) — landing distinta por vertical.
- **Precio:** desde ~US$600/mes (objetivos bajos) hasta ~US$4,000/mes (objetivos
  agresivos). Modelo alternativo: pago por reunión agendada ("ROI garantizado").
- **Señal relevante:** promete integrarse "como parte del equipo de ventas" en
  menos de 1 mes — velocidad de onboarding como argumento de venta.
- Fuente: leadfishers.co (2026-07-03).

### B2B Rocket (AI agents, global con alcance LATAM)
- **Qué hace:** plataforma de agentes de IA que automatiza el ciclo completo:
  define ICP + propuesta de valor + secuencia → el agente busca prospectos en
  su base de contactos, redacta outreach personalizado, responde objeciones y
  agenda reuniones. Es el competidor más cercano al enfoque de ZERO (orquestación
  de agentes vs. servicio manual de agencia tradicional).
- **Features clave:** follow-ups adaptados a comportamiento (aperturas, clics,
  sentimiento), multicanal (email/llamadas/social en planes altos), integración
  con CRMs (Salesforce, HubSpot, Zoho, Zapier), pool de 10,000+ mailboxes
  pre-calentados para entregabilidad.
- **Precio:** plan "Growth" US$2,450/mes (5 agentes IA, ~6,000 leads/mes, ~27,000
  emails/mes); plan "Scale" US$4,199/mes (10 agentes, ~12,000 leads/mes, ~54,000
  emails/mes). Oferta activa: 50% off primer año.
- **Señal relevante:** vende explícitamente "agentes IA" como unidad de escala
  (más agentes = más volumen) — mismo lenguaje de producto que ZERO, pero sin
  el enfoque de calificación estricta (gate) que tiene nuestro pipeline.
- Fuente: b2brocket.ai/pricing (2026-07-03).

### AiSDR (AI SDR, plataforma self-service global)
- **Qué hace:** herramienta de AI SDR que cobra por volumen de mensajes, no por
  asiento — "unlimited seats" en todos los planes. Automatiza secuencias de
  outreach con contenido multimedia generado por IA (videos cortos, notas de
  voz, memes insertados en las secuencias) en el plan superior.
- **Precio:** plan "Explore" US$900/mes (1,200 mensajes IA + créditos de
  búsqueda de leads); plan "Grow" US$2,500/mes (4,500 mensajes + 4,500 créditos,
  incluye contenido multimedia); "Enterprise" a medida. Facturación trimestral
  por defecto, 20% descuento si se paga anual. Sin contrato de permanencia —
  cancelación en cualquier momento.
- **Señal relevante:** es el punto de entrada más barato visto hasta ahora entre
  plataformas de agentes IA (US$900/mes vs. US$2,450/mes de B2B Rocket) — el
  modelo "self-service, cancela cuando quieras" compite directo con el tramo
  bajo de agencias tradicionales chilenas, pero sin trato humano ni CRM propio.
- Fuente: aisdr.com/pricing (2026-07-04).

### Adstrategy (México/global, performance marketing CPL)
- **Qué hace:** agencia de performance marketing con 10-11 años de trayectoria,
  enfocada en generación de leads (CPL) y ventas (CPA) para B2B y B2C en más de
  30 países (LATAM + Europa). En B2B genera +30,000 leads calificados/mes en
  sectores como seguridad, energía, tecnología y telemática.
- **Posicionamiento:** "AI Lead Generation" en su marca, pero el modelo de
  negocio real es cost-per-lead — el cliente paga solo por lead válido
  entregado, no por gestión mensual ni por agente.
- **Precio:** no público; modelo CPL variable según industria y volumen.
- **Señal relevante:** el pricing por CPL (pago solo por resultado, sin
  retainer fijo) es un modelo distinto al de suscripción mensual de Lead
  Fishers/B2B Rocket/AiSDR — vale la pena vigilar si esto gana tracción como
  alternativa de menor riesgo percibido para el cliente.
- Fuente: adstrategyglobal.com, LinkedIn Adstrategy (2026-07-04).

### Clay (capa de orquestación GTM, no agencia ni AI SDR todo-en-uno)
- **Qué hace:** plataforma de "arma tu propio stack" — enriquece listas de leads
  combinando 100+ proveedores de datos en cascada, corre prompts de IA fila por
  fila para generar variantes de mensaje personalizadas, y se integra con
  herramientas de envío (p.ej. Smartlead) que hacen el disparo y cuidan la
  entregabilidad. No entrega leads ni gestiona el outreach por sí sola — es la
  capa de "pegamento" entre datos, IA y envío.
- **Categoría distinta a lo ya registrado:** Lead Fishers/Adstrategy son
  agencias con servicio humano; B2B Rocket/AiSDR son productos todo-en-uno de
  agente IA. Clay es infraestructura componentizada — el cliente (o una
  agencia) arma su propio pipeline con ella, no un servicio cerrado. Vale la
  pena vigilarla porque es el modelo más parecido en filosofía a la arquitectura interna de ZERO
  (`discovery.py` + `backends.py` como piezas intercambiables), pero Clay lo
  vende como producto self-service en vez de operarlo como servicio gestionado.
- **Precio:** plan gratuito (100 créditos de datos + 500 acciones/mes); "Launch"
  US$185/mes (10,000 créditos + 2,500 acciones); "Growth" US$495/mes (6,000
  créditos + 40,000 acciones, incluye auto-sync a CRM); "Enterprise" a medida.
  Bajó precios de datos 50-90% en marzo 2026 tras renegociar con proveedores.
- **Señal relevante:** el pricing 100% basado en uso (no por asiento) confirma
  la tendencia que ya vimos en AiSDR — el mercado se está moviendo hacia cobrar
  por volumen de trabajo hecho, no por licencia de herramienta.
- Fuente: clay.com/pricing, resúmenes agregados de terceros (2026-07-05).

### Smartlead (infra de envío de cold email, modelo white-label para agencias)
- **Qué hace:** plataforma de envío de cold email (no busca ni califica leads —
  solo dispara y protege entregabilidad) con arquitectura multi-tenant: cada
  cliente de la agencia queda en un workspace aislado para que un problema de
  reputación de un cliente no contamine a los demás.
- **Modelo de reventa:** desde el plan "Pro" (US$94/mes) una agencia puede
  agregar sub-cuentas de clientes pagando un add-on de white-label de
  US$29/mes por cliente — la agencia revende la plataforma bajo su propia
  marca sin que el cliente sepa que corre sobre Smartlead.
- **Precio base:** "Base" US$39/mes, "Pro" US$94/mes, "Unlimited Smart"
  US$174/mes (plan más popular), "Unlimited Prime" US$379/mes.
- **Importancia para ZERO: 8/10.** No es un competidor directo (no ofrece
  calificación ni CRM), pero el modelo white-label es la pieza que le falta a
  cualquier agencia chilena/LATAM para ofrecer "su propia" plataforma de
  outreach sin construir nada — reduce la barrera de entrada para que un
  competidor tipo Lead Fishers o una agencia nueva monte algo que se vea como
  un producto propio a bajísimo costo (US$29-379/mes vs. construir un backend).
  Vale la pena vigilar si algún competidor empieza a venderse como "plataforma
  propia" y en realidad es una reventa de esta capa.
- Fuente: smartlead.ai/pricing (2026-07-06).

### Panorama general de precios (referencia, no una empresa específica)
- Agencias regionales chilenas/LATAM tradicionales (SEO/Ads + lead-gen):
  desde US$500/mes (objetivos bajos) hasta US$1,500–4,000/mes (agresivo).
- Agencias globales con presencia LATAM (Belkins, Martal Group, Callbox,
  Vsynergize): retainers mucho más altos, US$4,000–15,000/mes, algunas con
  mínimos de proyecto de US$10,000+. Apuntan a empresas con presupuesto de
  marketing corporativo, no a PyMEs.
- Fuente: búsquedas agregadas Sortlist/Semrush/directorios (2026-07-03).

---

## Notas de interpretación

- El hueco de precio entre agencias tradicionales chilenas (US$500–1,500/mes,
  trabajo manual) y plataformas de agentes IA (US$2,450–4,199/mes, EE.UU./global)
  sugiere espacio para un punto medio: automatización con agentes IA a precio
  de agencia regional. Ningún competidor visto hasta ahora combina ambas cosas
  con foco explícito en Chile/LATAM.
- B2B Rocket es la referencia más cercana en lenguaje de producto ("agentes IA")
  pero no menciona un gate de calificación estricto ni CRM propio — vende
  volumen de leads/emails, no necesariamente calidad garantizada.
- AiSDR baja el piso de entrada de las plataformas de agentes IA a US$900/mes
  (vs. US$2,450 de B2B Rocket), compitiendo directo con el tramo bajo de
  agencias tradicionales chilenas — esto reduce el "espacio en blanco" que
  identificamos en el ciclo anterior, aunque sigue sin combinar precio bajo +
  foco LATAM + gate de calidad explícito.
- Adstrategy muestra que el modelo CPL (pago solo por lead válido, sin
  retainer) también compite en este mercado — es un modelo de riesgo distinto
  al de suscripción que usan Lead Fishers/B2B Rocket/AiSDR, y podría ser más
  atractivo para clientes reacios a comprometerse con un fee mensual fijo.
- Clay confirma que hay un tercer arquetipo de competencia además de "agencia
  con servicio humano" y "producto todo-en-uno de agente IA": infraestructura
  self-service que el cliente (o una agencia) compone por su cuenta. No compite
  directo con ZERO como entrega gestionada, pero sí es la opción que un cliente
  técnico podría elegir para construir algo parecido por su cuenta a menor
  costo — argumento a favor de que la ventaja de ZERO esté en la operación
  gestionada + el gate de calidad, no solo en la arquitectura modular.
