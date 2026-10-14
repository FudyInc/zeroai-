# Motor del agente de WhatsApp

**El PDF del catálogo se entregó por primera vez 2026-10-14:** tras la
activación, «Catalogo bordes» no obtuvo respuesta. El mensaje llegó y el ruteo
al PDF funcionó; el puente respondió `403 catalog document not allowed for this
account` y el evento quedó en revisión. LosetasChile corre en el puente **por
defecto**, que arranca sin `WHATSAPP_WEB_CLIENT_ID`, de modo que `clientId`
queda vacío y tres rutas lo comparaban en estricto contra `losetaschile`: el PDF
del catálogo, la encuesta de despacho y la captura del voto. La ruta de imágenes
no tiene esa guarda, y por eso el enlace y las fotos siempre funcionaron y el
fallo pasó inadvertido. El mismo 403 ya estaba registrado a las 03:06, antes de
la activación: el documento nunca se había entregado, y ningún evento
`completed` pudo haberlo enviado porque la guarda rechazaba todos los intentos.

`actsFor` admite ahora un puente sin nombre y sigue rechazando uno de otra
empresa; la autorización real sigue en Python, que exige la empresa y verifica
el número conectado. Contra el puente en marcha, la petición que daba 403
devolvió 400 por validación del destinatario, sin enviar nada. Diego confirmó
después la recepción del PDF en su teléfono —evento `completed` a las 23:03:15,
sin error—, la primera entrega real comprobada del documento.

Queda un problema de presentación: nueve de las once fotos son capturas
verticales de 591×1280 y el marco de 200×200 con `object-fit: cover` descarta
un 54% de cada una. Solo Gregioriano y Octagonal Piedra, casi cuadradas, se ven
completas. Diego preparará material nuevo; falta decidir si se recorta el origen
o se rearma la maqueta.

**Saludo por hora y gate de respuesta activados 2026-10-14:** el trabajo del
worktree `motor-whatsapp` quedó versionado en cuatro commits sobre `0fdb494`.
Al comparar con el backend activo apareció una brecha: desde el 2026-10-11 solo
se habían copiado los parches del catálogo, así que el saludo según la hora de
Chile, el gate `check_reply`, la ubicación de LosetasChile como dato de despacho
y la recuperación de seguimiento seguían sin correr en producción, tal como
decían sus propias notas de «código local».

La activación se hizo por fusión de tres vías, no por copia: el checkout activo
tenía trabajo propio sin commitear en `import_ad_leads` —deduplicación de Meta
Lead Ads por `meta_lead_id`— que una copia del archivo habría borrado. El único
conflicto real era el import de `whatsapp_greeting`. La fusión se validó en una
copia aislada del checkout activo con 1114 pruebas en verde; el estado
commiteado del worktree pasó 1104 pruebas Python, dos pruebas Node del PDF y
una de la recuperación. El backend reinició a PID 317056 con salud OK y el
puente quedó `ready` con la cuenta de LosetasChile. Desde el código activo se
comprobaron los cuatro tramos del saludo, la corrección de un saludo
incongruente, las dos grafías informales de catálogo, tres frases que no
autorizan envío inmediato, el gate ante respuesta vacía y el formato en
párrafos. La suite no se corrió dentro del checkout activo porque ahí están
`state.json`, `crm.json` y las credenciales de Supabase. No se envió ningún
mensaje de prueba. Falta una conversación real que muestre el saludo según la
hora y la apertura de ambos PDF en el teléfono. El checkout activo conserva un
`tests/test_visual_catalog.py` sin versionar que importa un símbolo ya
inexistente: es el único error de su suite.

**Solicitudes reales de catálogo con escritura informal — corrección local 2026-10-14:**
Dos mensajes nuevos, «Catalogo bordes» y «Cagalogo de pastelones», quedaron
completados en la cola local, pero no activaron la ruta de PDF. Diego reportó
una respuesta que mencionaba el dashboard. Se añadió una prueba de regresión
con ambas frases y se ajustó la detección de categoría; una petición pospuesta
o una pregunta de disponibilidad sigue sin enviar el documento. La corrección
se cargó en el backend local activo el 2026-10-14 con respaldo en `/tmp`; el
servicio reinició y respondió salud OK. Falta una prueba nueva de entrega y
apertura en el teléfono.

**Catálogos PDF separados de LosetasChile — verificación local 2026-10-14:**
Una petición explícita por el catálogo de bordes o pastelones prepara un PDF
distinto de una página y lo envía como un solo documento por WhatsApp Web.
La petición genérica de «Catálogo» conserva el enlace general. Flor de lis queda
fuera por confirmación de Diego y Adoquín se omite mientras no se confirme su
vigencia. Los archivos no son fichas nativas seleccionables ni colecciones de
WhatsApp Business. Si el envío queda incierto, se revisa el chat antes de
reintentar. El código del generador y del puente coincide con el checkout del
backend local; la API respondió `/api/health` OK y pasaron 1102 pruebas Python
y dos pruebas Node de la plantilla del PDF el 2026-10-14. La consulta autenticada del estado del
puente devolvió 401 desde este checkout, por lo que su estado actual no quedó
revalidado en esta comprobación. Falta verificar recepción y apertura de ambos
PDF en el teléfono; no se comprobó despliegue remoto.

**Catálogo en español y recuperación 2026-10-13 (backend local activo):**
Diego confirmó que recibió el enlace del catálogo tras recuperar manualmente un
mensaje «catalogo» que el puente Web no había registrado mientras estuvo más de
diez minutos en `connecting`. El servicio reinició y el puente volvió a `ready`.
El agente ahora responde a una petición explícita con dos líneas:
`Catálogo` y el enlace de WhatsApp, sin texto comercial adicional. El envío pide
suprimir la vista previa para evitar la tarjeta «View Zero's catalog on
WhatsApp», cuyo idioma controla WhatsApp. El 2026-10-13 a las 12:54 Chile se
envió una prueba al mismo chat confirmado: el puente aceptó el mensaje y
después registró `ack=3`; falta que Diego confirme la apariencia en su teléfono.

El puente reinicia su conexión si queda 120 segundos sin estar listo y, al
reconectar, revisa los mensajes entrantes individuales visibles en la caché de
los últimos 30 minutos. Evita reencolar mensajes anteriores a una salida en el
chat; el almacén de eventos del backend deduplica IDs. Esta recuperación no
garantiza rescatar mensajes fuera de la caché ni sustituye una prueba real de
una desconexión nueva. Se separaron los procesos Node y Chromium para limpiar
ambos antes de reiniciar. Pasaron 1098 pruebas Python, tres pruebas Node,
comprobación de sintaxis y `git diff --check`; el backend local respondió OK,
el puente quedó `ready` con la cuenta de LosetasChile y cola entrante vacía.
Una foto enviada como imagen común no ofrece selección de productos; el
catálogo nativo de WhatsApp sí permite abrir y elegir artículos. El puente
actual envía texto, enlace e imágenes, pero no implementa el envío automático
de fichas de producto nativas. Esto queda pendiente si Diego lo solicita.

**Histórico: catálogo sin signos y respuestas legibles 2026-10-12:**
La prueba reciente «Catalogo» llegó al puente, pero la regla exigía un signo de
pregunta o más palabras y el modelo respondió con otro texto. Ahora esa palabra
sola, con o sin tilde, activa únicamente el enlace del catálogo. Las peticiones
que posponen el envío («pero no ahora», «no me lo mandes hasta mañana») siguen
sin dispararlo. Las respuestas normales de LosetasChile separan las oraciones
en párrafos cortos cuando el texto es largo y completan la puntuación final;
los enlaces solos y mensajes con estructura previa se conservan. El prompt
también pide frases breves y párrafos claros. El puente permite consultar el
estado `ack` de cada mensaje en la API autenticada. En el chat reciente examinado,
las salidas tienen `ack=3` (leído en WhatsApp Web), pero Diego aún no confirmó
que ese sea el chat de su prueba: falta identificarlo con las últimas cuatro
cifras y texto exacto. Pasaron 1097 pruebas completas y 75 dirigidas, más la
revisión de sintaxis Node y del parche. El backend local reinició a las 16:48
Chile (PID 52380); API OK y puente Web `ready`, sin entradas pendientes ni error.
Una entrega al teléfono de la prueba correcta sigue pendiente de confirmación.

**Histórico: catálogo solo enlace 2026-10-12:**
Diego probó el parche anterior y recibió una respuesta demasiado larga. Una
solicitud explícita de catálogo de LosetasChile ahora produce solo
`https://wa.me/c/56964537891`, sin saludo, lista de modelos, pregunta,
cotización, imagen ni encuesta. Rige también cuando el mensaje combina catálogo
con despacho o presupuesto; esas otras consultas pueden seguir en mensajes
posteriores. «¿Qué modelos hay?» conserva la respuesta de modelos si no pide el
catálogo explícitamente. La detección omite negativas y menciones que no piden
el enlace; una oferta pendiente no sustituye la petición por un resumen largo.
Pasaron 53 pruebas dirigidas y la suite completa de 1094 pruebas. El parche se
aplicó en `/home/diego/zeroai`; el proceso reinició a las 16:38 Chile, la API
respondió OK y el puente Web quedó `ready` sin errores. Falta una prueba en el
teléfono de la respuesta reducida.

**Diagnóstico de la falta de respuesta 2026-10-12:** antes de la corrección,
«¿tienen catálogo?» y «¿me mandas el catálogo?» no activaban el enlace. El
primer parche se cargó en el backend local a las 16:15 Chile; salud y puente Web
quedaron bien. Diego confirmó después que sí recibió una respuesta, pero era
demasiado larga. Los cuatro eventos revisados antes no eran el mensaje que
quería investigar. Supabase activo mostró modo automático y cero pausas de
atención humana para LosetasChile; el chat exacto sigue sin identificar.

**Saludo según hora de Chile 2026-10-11 (código local):** WhatsApp usa la zona
`America/Santiago` para elegir «Buenos días» entre 05:00 y 11:59, «Buenas
tardes» entre 12:00 y 19:59 y «Buenas noches» entre 20:00 y 04:59. Si el
contacto escribe «buenas tardes» de noche, el agente responde «buenas noches».
Los saludos simples y la respuesta de recuperación usan la misma regla; el
modelo recibe el saludo calculado y se corrige un saludo inicial incongruente.
Esto describe la hora del mensaje, no el horario de atención del negocio.
La suite local de 1091 pruebas aprobó el cambio. Prueba en servicio activo y
conversación real pendientes.

**Control de respuestas y entradas 2026-10-11 (código local):** el motor local
revisa el texto generado antes de adjuntar un presupuesto calculado. Ante un
texto inválido reintenta una vez; si persiste, deriva ese mensaje a revisión y
envía el aviso habitual en vez del borrador. La entrada Meta conserva el título
visible de selecciones de botones y listas; otros adjuntos sin texto legible se
derivan a revisión. Las ubicaciones de LosetasChile mantienen su flujo de
presupuesto con coordenadas válidas; las ubicaciones Meta incompletas y las de
otras empresas se derivan a una persona. La suite local de 1086 pruebas aprobó
este recorrido. Prueba real con
modelo, ficha activa y transporte WhatsApp pendiente; no hay despliegue
verificado de estos cambios.

**Auditoría de comprensión 2026-10-11 (código local):** la selección de la ficha
para el modelo local separa cada oferta de una lista y usa el último intercambio
al resolver preguntas de seguimiento, sin desplazar un tema nuevo. «Flete» se relaciona con la
política de despacho. La ficha ZeroAI versionada se comparó con el almacén
local: no hay ficha activa en ese `state.json`; no se cargó ni se modificó el
almacén. Suite local de 1078 pruebas aprobada. Falta verificar respuestas con el
modelo en una conversación real y comprobar la ficha activa de producción.

**Código activo y pruebas locales:** 2026-10-07. El backend reinició con
`main` en `5566e10` y respondió a `/api/health`. GitHub recibió el código y
Vercel informó un despliegue de producción `Ready` el mismo día.
**Almacén de producción:** ficha ZeroAI y conexión Meta comprobadas.
**Conversación real:** Diego confirmó respuestas en el WhatsApp de LosetasChile
el 2026-10-06 23:41 Chile, antes de la corrección del cálculo de bordes.
El catálogo activo de LosetasChile ya incluye el esquinero; el subtotal de
productos de un pedido 6 × 3 m se calculó con historial y precios reales en una
simulación sin envío. El 2026-10-07 se observó un subtotal real por WhatsApp
tras «Okay el presupuesto»; lo calculó el código activo, no Qwen 3. Falta una
conversación real de ZeroAI por Meta.

**Flujo de LosetasChile activo en el backend local 2026-10-08:** la imagen
entregada por Diego muestra siete colores etiquetados. El agente puede enviarla
por WhatsApp Web, recoger el color elegido y preparar un presupuesto interno
con nombre de perfil opcional y número obligatorio. Ese presupuesto no se envía
automáticamente al cliente. Diego creó «Presuouesto losetas ia»; se verificó
como grupo separado de «Losetas Diego» en la cuenta Web asignada. Se configuró
como destino en el servicio local y se confirmó un mensaje técnico aceptado y
visible en el grupo, sin datos de clientes. Pasaron 1048 pruebas Python y la
revisión de sintaxis del puente. Falta comprobar el recorrido real de imagen,
elección de color y presupuesto con un mensaje nuevo desde el teléfono de Diego.
El cambio aún no se publicó en GitHub ni en Vercel.
Diego confirmó después que la prueba técnica llegó al grupo correcto.
En el primer intento del recorrido desde el cliente, el mensaje entrante
quedó registrado pero el chat ya tenía una pausa automática por una consulta
anterior no interpretable. No se envió respuesta. La pausa de ese chat de
prueba se liberó y se comprobó el estado nuevo el 2026-10-08; el mensaje
anterior no se reprocesó. Falta un mensaje nuevo con las medidas completas.

**Ajustes activos en el backend local el 2026-10-08:** las consultas por
bordes de piscina sin largo y ancho preguntan primero por las medidas en
metros. La respuesta a esa pregunta continúa el flujo sin depender del modelo.
Diego prefirió Qwen 3 de 14B tras la prueba temporal y pidió dejarlo como
modelo habitual de WhatsApp. Se añadió una configuración específica del canal
para mantener Qwen 2.5 en los otros agentes. El servicio reinició con
`WHATSAPP_MODEL=qwen3:14b`, `/api/health` respondió OK, el puente Web quedó
`ready` y `ollama ps` mostró Qwen 3 en GPU. Una simulación sin envío devolvió
respuesta de Qwen 3 y otra preguntó por medidas cuando faltaban. Pasaron 1053
pruebas Python. La muestra previa fue pequeña y Qwen 3 tardó más (la nueva
simulación demoró unos 24 s). Falta verificar un mensaje nuevo de extremo a
extremo por WhatsApp para la pregunta de medidas ausentes. Estos ajustes no se
han publicado en GitHub ni Vercel.

**Prueba real de imagen 2026-10-08:** la consulta de bordes 6 × 3 llegó al
backend, pero `whatsapp-web.js` falló al construir la imagen por una colisión
de su ID interno de medios con el del mensaje. Coincide con el reporte
<https://github.com/wwebjs/whatsapp-web.js/issues/201922>. Se aisló ese campo
en el puente. Una reanudación manual, tras comprobar que no había imagen en el
chat, creó una imagen con descripción correcta; WhatsApp mostró acuse 2. El
puente la marcó incierta porque comparaba la descripción con `body`; se cambió
la confirmación para usar `caption`. Se comprobó la imagen entregada, se
registró la pregunta de color en la conversación y se cerró solo el último
evento. No se envió una copia adicional. Diego confirmó la imagen y respondió
«gris». El evento quedó completado; el presupuesto fue visible en «Presuouesto
losetas ia» con nombre sobre número, 36 bordes, 4 esquinas, color gris, total
de productos $230.400 y despacho por cotizar. En el chat del cliente no se
observó subtotal automático. Falta comprobar la pregunta por medidas ausentes
desde un chat sin historial y un envío nuevo de imagen con confirmación del
puente sin intervención manual.

**Acuse de color 2026-10-08:** Diego reportó que no recibió mensaje tras
responder «gris». El silencio era el comportamiento anterior: el presupuesto
solo se mandaba al grupo. El backend local ahora envía una confirmación breve
del color después de la aceptación por el grupo, sin mostrar importe alguno.
Si ese acuse falla, el evento queda para revisión; la firma del presupuesto
ya está guardada y evita un segundo envío al grupo. Una sola confirmación del
caso existente se entregó al chat de prueba con acuse 2 y quedó registrada en
la memoria activa. El subtotal continuó ausente del chat del cliente. La suite
Python completa aprobó 1054 pruebas. Falta ver el nuevo acuse automático en un
pedido posterior.

**Prueba temporal de Qwen 3 2026-10-07:** el backend WhatsApp usó Qwen 3 de
14B durante una prueba desde el teléfono de Diego. Se observó un saludo y una
respuesta de subtotal; el subtotal vino del cotizador activo y no mide la
calidad del modelo. Se restauró Qwen 2.5; `/api/health` y el puente Web
respondieron correctamente. El resto de agentes mantuvo su modelo.

**Evaluación de modelo local 2026-10-07:** el servicio sigue configurado con
`qwen2.5:14b-instruct-q4_K_M`. La máquina tiene una RTX 5060 Ti de 16 GB.
Se descargó `qwen3:14b` para una comparación local sin mensajes a clientes ni
cambio del backend. Con la ficha versionada de ZeroAI en memoria temporal,
ambos respondieron cuatro consultas comerciales sin cifras o garantías
inventadas. Qwen 2.5 tardó 2,3–9,6 s por consulta; Qwen 3 tardó 5,6–19,5 s
con razonamiento y 5,5–12 s sin él. La muestra es pequeña y no prueba una
mejora general. El modelo activo volvió a quedar cargado en GPU. Para evaluar
un modelo de mayor tamaño en esta máquina hace falta considerar más VRAM;
queda pendiente una comparación representativa antes de cambiar producción.

**Incidente 2026-10-07:** una conversación real de LosetasChile respondió
«alrededor de 18 pastelones» a «Necesito pastelones». Esa frase no pedía un
cálculo y llegó al LLM. Diego precisó que, con el pedido ya confirmado, el
motor debe guardar las cantidades y enviar el presupuesto con total, sin
explicar las piezas en una frase suelta. La corrección local usa el cotizador
estructurado y deriva cifras no respaldadas del modelo a revisión. Queda
pendiente su publicación y comprobación en una conversación nueva.

**Comprobación 2026-10-07:** el backend respondió a `/api/health` con el
subtotal de productos y la segunda corrección de bordes ya en `main`. Después
se integró `6147176`, que mejora el contexto y la revisión de consultas. La
revisión del cotizador encontró dos consultas de precios no cubiertas. Su
corrección quedó activa en el backend con `5566e10` y se publicó en `main`;
queda pendiente una prueba real de la respuesta.

El código integrado admite Meta Cloud y sesiones WhatsApp Web asignadas por
negocio. El envío real exige credenciales propias del negocio. ZeroAI ya tiene
sus claves Meta por negocio; LosetasChile conserva su sesión WhatsApp Web.

El webhook de Meta valida el mensaje, obtiene el ID del número receptor y, si Meta
lo entrega, el nombre del perfil del remitente. El ID receptor determina la empresa
antes de buscar al contacto en el CRM. Si dos empresas comparten receptor, el
motor responde solo si el remitente ya existe en una única empresa asociada.
Ante dos coincidencias o un remitente nuevo no elige una por su cuenta.
Con varias empresas, un receptor desconocido
tampoco se asigna a ZeroAI salvo que coincida con el receptor global configurado.
El número global de Meta busca primero un contacto existente entre las empresas
que usan ese número; si hay una sola coincidencia, usa su ficha. Si hay varias,
no responde. Para un contacto nuevo conserva el cliente predeterminado. Una
empresa con número propio no entra en la búsqueda del número global.
Un receptor asignado a un vendedor sin empresa asociada también queda sin respuesta.
Un nombre de perfil
completa un nombre vacío; nunca reemplaza uno ya guardado. Si no hay nombre, el
primer saludo usa «Estimado/a».

Los mensajes y respuestas enviadas quedan en la memoria por empresa y contacto.
CONCIERGE recupera turnos relevantes del historial completo y envía un contexto
compacto al modelo local. Una respuesta cuyo envío falló no se agrega como turno
del agente, y una oferta pendiente
no se marca cumplida si falló el envío. Con `OUTBOX_LIVE=1`, la falta de
credenciales Meta produce un error de envío, no un resultado simulado como enviado.

El 2026-10-07 se detectó que «Ya revisé tu consulta» escapaba al control de
afirmaciones de revisión. La corrección incorpora ese borrador real como
regresión, conserva modelo, medidas y ubicación en chats largos y permite un
saludo después de una revisión automática con aviso. Está desplegada en el
backend local: salud OK y puente WhatsApp Web en estado `ready`. La secuencia
se comprobó con pruebas controladas, sin enviar mensajes a clientes; queda
pendiente observar una conversación real posterior al despliegue.

PoolEdge aún no tiene conectado el cotizador de despacho. Por eso, una consulta de
precio recibe una solicitud de datos sin pasar por el modelo ni adjuntar un total.
La plantilla de `docs/plantilla-presupuesto-pooledge.md` sigue pendiente de integrar.
El cotizador directo `/api/quote` también rechaza el presupuesto de PoolEdge
hasta que exista la revisión del despacho.

La versión integrada está activa en el backend, pero la prueba de webhook vacío
no confirma entrega de una conversación real. La ficha activa de ZeroAI en
Supabase coincidió con la versionada (3982 caracteres); Graph API reconoció el
número Meta. PoolEdge no figura como cliente activo. No se mostraron secretos,
números ni datos de leads durante estas comprobaciones.

### Catálogos visuales LosetasChile — 2026-10-13

La solicitud explícita de bordes o pastelones se enruta a un PDF distinto
por categoría, con fotos originales y nombres y precios estructurados.
Cada PDF ocupa una página y se envía como un solo documento de WhatsApp.
El de bordes reúne las tres fotos iniciales y dos fotos propias nuevas para
Borde ballena 50×40 ($5.500 por unidad confirmado en el almacén activo):
una instalación y un detalle del material. El de pastelones reúne seis fotos.
La extensión sin precio estructurado queda por confirmar. La carpeta recibida
quedó archivada en `entregables/fotos-losetas-recibidas-2026-10-13/`.
La generación local y la suite se comprobaron el 2026-10-13. Las fotos de
Borde ballena se activaron en el backend local el 2026-10-14, con salud OK y
puente Web de LosetasChile listo. La entrega en el teléfono del cliente aún
no se ha comprobado.

El 2026-10-14 se ajustó el orden de la tarjeta de Borde ballena: foto de la
pieza, seguida de la piscina instalada. Los precios de ambos catálogos se
muestran bajo el nombre, en negrita y con «x unidad». La vista previa de
bordes y los dos PDF de una página se comprobaron localmente. El formato nuevo
se activó en el backend local: salud OK y puente LosetasChile ready. La entrega
en WhatsApp sigue pendiente de comprobación real.

## Comprobación 2026-10-06

El servicio activo cargó claves Meta propias de ZeroAI: el handshake y un POST
firmado sin mensajes respondieron correctamente. El puente Web de LosetasChile
quedó en estado ready tras recargar el backend. Esta prueba no demuestra una
conversación real entregada.

El contexto local activo recupera secciones de la ficha y
datos del contacto de turnos antiguos dentro del límite del modelo. Una afirmación
de cotización ya revisada sin evidencia deriva a revisión humana. Pasaron 998
pruebas Python y 6/6 casos del modelo local; una conversación inventada produjo
una respuesta sin repetir las medidas. El backend respondió a salud, handshake
Meta, POST firmado vacío y estado Web ready. Falta probar una conversación real
de extremo a extremo, sin reintentar el mensaje de entrega incierta del 2026-10-05.
