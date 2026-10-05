# WhatsApp Web local para ZERO

Este puente usa el mismo número de WhatsApp Business como dispositivo vinculado.
Escanea el QR desde **WhatsApp Business → Settings → Linked devices → Link a device**.
El backend y el puente corren en la misma máquina; el puerto 8810 escucha solo en
`127.0.0.1`. El QR se muestra únicamente en la página WhatsApp del dashboard,
tras iniciar sesión.

El número 8810 pertenece al cliente indicado por `DEFAULT_INBOUND_CLIENT_ID`.
Para un segundo cliente, configurar `WHATSAPP_WEB_CLIENT_PORTS` como JSON, por
ejemplo `{"zeroai":8811}` cuando Losetas Chile usa el número principal. Cada
puerto abre una sesión privada separada y la página de WhatsApp muestra el QR
del cliente seleccionado. No registrar el mismo número en dos clientes.
No incluir al cliente predeterminado en `WHATSAPP_WEB_CLIENT_PORTS`: ya usa el
puerto principal 8810. Cada evento entrante debe incluir el número receptor;
si el puente aún no lo conoce, conserva el evento y lo completa al conectarse.

## Bandeja de chats

La página WhatsApp muestra los chats del número vinculado a la empresa seleccionada.
El backend comprueba que el número de la sesión coincide con el asignado a esa
empresa antes de consultar mensajes o responder. Los grupos se pueden leer, pero
la respuesta manual desde el dashboard se limita a chats individuales.

Una respuesta manual usa la misma confirmación de aceptación del puente que las
respuestas del agente. Esa confirmación no acredita entrega al teléfono. Si el
puente no devuelve un identificador de mensaje, la API informa un error y no
registra la respuesta como aceptada en el CRM.

## Configuración

1. Instalar dependencias con `npm install --prefix whatsapp-web-bridge --ignore-scripts`.
   Se usa Chromium ya instalado; no se descarga otro navegador.
2. Generar un secreto aleatorio de al menos 32 caracteres y configurar el mismo
   `WHATSAPP_WEB_BRIDGE_TOKEN` para backend y puente.
3. Configurar `WHATSAPP_PROVIDER=web` y `WHATSAPP_WEB_CHROME` con la ruta a
   Chromium. Mantener `OUTBOX_LIVE=1` únicamente cuando se deseen respuestas
   reales. El remitente Web rechaza campañas y plantillas.
4. Iniciar el backend de ZERO. El backend arranca y supervisa el puente.
5. Abrir WhatsApp en el dashboard y escanear el QR. El estado debe pasar a
   `ready` antes de probar un mensaje entrante.

Si los avisos internos llenan el mismo chat, configurar
`OWNER_WHATSAPP_PAUSED=1`. Esto mantiene las respuestas a leads y conserva
los avisos por correo. En la instalación de producción, el script
`python3 /home/diego/zero-core/scripts/activar-whatsapp-web.py --activate`
reactiva el envío después de comprobar que el backend y el dispositivo están listos.

La sesión queda en `whatsapp-web-bridge/.session/`, excluida de Git. Guardar
esa carpeta con permisos privados. Al cambiar de máquina o borrar la sesión
será necesario escanear otro QR.

Los mensajes que el backend todavía no acepta quedan en
`whatsapp-web-bridge/.session/inbound-pending.json` y se reintentan tras reconectar.
Una vez aceptados, el backend los guarda en `whatsapp-web-events.sqlite3` antes de
responder al puente. El trabajador procesa los pendientes después de reiniciar.
Si el proceso se interrumpe durante un envío o el puente no confirma la respuesta,
el evento queda como `needs_review`: se revisa en el CRM antes de reenviarlo para
evitar respuestas duplicadas. `scripts/revisar-salud.py` avisa por correo si hay
eventos en ese estado, mensajes pendientes o si el puente deja de estar listo.

Este conector no es la Cloud API oficial. WhatsApp puede cerrar sesiones o
restringir el número; no hay garantía de disponibilidad. El número de WhatsApp
Business sigue en la app del teléfono y no requiere comprar otra línea.
