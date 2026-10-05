# Adaptación del agente de WhatsApp por empresa

Estado revisado: 2026-09-29. Esta nota describe el código de `zero-core`; no certifica
que los cambios ya estén desplegados en el backend o dashboard públicos.

## Lo que ya existe

| Componente | Estado en core |
| --- | --- |
| Ficha de conocimiento | Separada por `client_id`, con versiones y restauración. |
| Catálogo de precios | Separado por `client_id`; cantidades, subtotal e impuesto se calculan en código. Moneda e impuesto editables. |
| Tono e instrucciones de atención | Perfil separado por `client_id`, usado por el agente de WhatsApp. La identidad del vendedor se puede reutilizar sin cambiar a otras empresas. |
| Prueba de conversación | Usa el mismo motor y prompt local que los mensajes entrantes; no envía ni guarda la conversación en CRM. |
| Conversaciones y leads | Se guardan bajo `client_id`. Para WhatsApp entrante con número receptor conocido, la búsqueda del contacto queda acotada a ese cliente. El agente recupera turnos anteriores pertinentes y recuerda solo frases explícitas del contacto. |
| Pruebas con conversaciones reales | Desde la conversación del dashboard se puede guardar una pregunta del contacto, junto con la respuesta esperada escrita por una persona, en el banco de casos de esa empresa. |
| Número receptor | Se puede vincular un número de WhatsApp a una empresa; se rechaza la duplicación y se detienen mensajes de destinos desconocidos. |
| Sesiones de WhatsApp Web | El puente principal sirve al cliente predeterminado. Se pueden configurar puertos y sesiones locales separados para otras empresas; cada vista consulta su propia sesión. |

## Límites que impiden ofrecer aún aislamiento completo

1. **Activación de cada sesión de WhatsApp Web.** El soporte para varios números requiere configurar un puerto por empresa, vincular el QR correspondiente y verificar con mensajes reales que cada respuesta sale del número asignado. Cambiar la empresa en el dashboard solo muestra su sesión; no vincula un número automáticamente.
2. **Reglas de cálculo particulares.** El cotizador actual cubre `cantidad × precio unitario + impuesto`. Descuentos por volumen, medidas, recargos de zona, escalas, mínimos, financiación y otras reglas requieren una configuración validada o un módulo de cálculo específico por negocio. Ningún monto debe depender de aritmética del modelo.
3. **Acceso entre empresas.** Los roles actuales son de la agencia; un usuario con acceso al dashboard puede seleccionar múltiples clientes. Para dar acceso a cada empresa a su propia cuenta hacen falta membresías por organización y filtros de autorización en todas las rutas y consultas, además de controles en la base de datos.
4. **Persistencia del estado.** Cuando se usa Supabase, el estado de varios clientes vive en una sola fila JSON (`app_state/agency`). Esto separa claves lógicas, pero no proporciona aislamiento transaccional ni protección ante escrituras concurrentes. Migrar a tablas por entidad con `tenant_id`, claves únicas y control de concurrencia.
5. **Conocimiento largo.** El agente local selecciona fragmentos de la ficha mediante coincidencia de términos dentro de un límite de 1600 caracteres. Para manuales, políticas o catálogos grandes aún conviene añadir documentos estructurados, metadatos de vigencia, fuentes visibles y pruebas de recuperación por caso.
6. **Activación.** Asignar vendedor, guardar reglas y conectar un número son pasos distintos. Hace falta un estado de preparación por empresa que valide número, ficha, precios, casos y una prueba real antes de marcarla activa.

## Secuencia recomendada para incorporar una empresa

1. Registrar su organización y usuarios con permisos exclusivos.
2. Capturar ficha, preguntas frecuentes, excepciones, tono y criterios de derivación a humano.
3. Cargar lista de precios y especificar con ejemplos cada cálculo particular; implementar y probar esos cálculos de forma determinista.
4. Vincular un número único y verificar que el mensaje entrante se enrute a esa empresa y que la respuesta salga del mismo número.
5. Crear un banco de casos que cubra ventas, presupuestos, datos faltantes, reclamos y límites del agente.
6. Probar en simulación y después con mensajes reales antes de activar el servicio.

## Regla operativa

No anunciar a una empresa como activa solo porque la ficha o el vendedor estén
asignados. El puente, el enrutamiento y las reglas de cálculo deben estar verificados
para esa empresa y su número.
