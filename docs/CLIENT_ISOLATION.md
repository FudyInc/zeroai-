# Aislamiento por negocio

**Verificación:** 2026-10-06, código y pruebas en un checkout aislado. El servicio
activo aún usa otro checkout; falta desplegar y probar una conversación real.

PoolEdge opera el dashboard y puede alternar entre negocios. El selector de negocio
determina las consultas y los envíos; no concede acceso a las credenciales de otro.

- Leads, CRM, bandeja de aprobación, búsqueda, campañas, funciones, ficha,
  precios y reglas del agente se consultan con `client`.
- El motor de IA y el catálogo base de personalidades son infraestructura común.
  Cada negocio añade su ficha, precios, tono, instrucciones y número de WhatsApp.
  Solo administración puede editar el catálogo base.
- Meta Ads, SMTP, Vapi y WhatsApp Cloud usan secretos con clave derivada del ID de
  negocio. El backend no toma credenciales globales como respaldo para tráfico de
  leads. `/api/integrations?client=...` informa estado sin devolver secretos.
- WhatsApp Web usa una sesión por negocio. La sesión principal existente pertenece
  al `DEFAULT_INBOUND_CLIENT_ID`; otras necesitan un puerto y sesión explícitos en
  `WHATSAPP_WEB_CLIENT_PORTS`. El número conectado debe coincidir con el perfil.
- El webhook Cloud verifica firma y Phone Number ID del mismo negocio antes de
  procesar mensajes. El webhook Web mantiene su firma propia.
- Los ajustes globales de modelo, almacenamiento, autenticación y envío real son
  infraestructura de la agencia. No identifican la conexión de un negocio.

Si un negocio no tiene credenciales de SMTP o Vapi propias, el envío o la llamada
fallan de forma visible. No se usa la credencial global antigua ni se simula éxito.
