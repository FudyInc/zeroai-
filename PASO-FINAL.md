# Tarea: dejar producción viva en WSL2 y liberar la partición Ubuntu

> Instrucciones para Claude Code en el PC de Diego (WSL2).
> Este archivo ES la tarea: léelo y ejecútalo.
> Anota tu avance en `PASO-FINAL-progreso.md` a medida que completes cada parte.

## CONTEXTO

`PASO-GPU.md` quedó completo: GPU operativa, `qwen2.5:14b-instruct-q4_K_M` en
VRAM, latencia 1.3-1.7s (antes 26-27s), 641 tests OK, Docker con todos los
flags del sandbox funcionando.

Falta **lo único que aún no está probado de punta a punta**: que un mensaje real
de WhatsApp reciba respuesta desde este entorno nuevo. Hasta que eso pase, la
partición Ubuntu bare-metal (211 GB) **no se toca** — es la única vuelta atrás.

## PARTE A — Levantar producción

1. **Authtoken de ngrok.** Verifica si existe `~/.config/ngrok/ngrok.yml`.
   Si no está, Diego lo saca de <https://dashboard.ngrok.com> (Your Authtoken)
   y se configura con `ngrok config add-authtoken <token>`. Es la misma cuenta
   de siempre: el dominio fijo `handpick-monogamy-spiny.ngrok-free.dev` está
   asociado a ella.
2. **Correr `deploy/install.sh`** para instalar los 4 servicios.
3. **Verificar que están activos**: `systemctl is-active zero-backend zero-tunnel`
   y `curl -s http://localhost:8800/api/health`.
4. **Verificar el túnel público**:
   `curl -s https://handpick-monogamy-spiny.ngrok-free.dev/api/health`
   Debe responder `{"ok":true,...}`. Si no, el problema está en ngrok, no en
   el backend.

## PARTE B — Mover el webhook y probar de verdad

5. Confirma que `TWILIO_WEBHOOK_URL` en el `.env` coincide **exactamente** con
   la URL que está puesta en la consola de Twilio. La firma se valida contra
   esa URL carácter por carácter; si difieren, todo llega como 403.
6. **Prueba sintética primero** (no gasta mensajes): POST firmado al webhook
   `/api/webhooks/twilio-whatsapp` con una firma HMAC-SHA1 válida construida
   con `TWILIO_AUTH_TOKEN`. Debe responder 200 y `X-Zero-Received: 1`.
   Comprueba también que una firma inválida da 403.
7. **Prueba real**: pídele a Diego que escriba por WhatsApp al sandbox
   (`+1 415 523 8886`) desde su teléfono. Verifica en el CRM que el mensaje
   entró y que salió una respuesta. **Mide el tiempo** desde que llega hasta
   que se envía la respuesta — con el 14b en GPU debería ser pocos segundos.

⚠️ Cuidado: `OUTBOX_LIVE=1` está activo, así que los envíos son **reales**.
Para pruebas sintéticas usa acciones internas (notas, etapas), nunca mensajes
a números que no sean el de Diego.

## PARTE C — Recién ahora: liberar los 211 GB

**Solo si A y B pasaron.** Si algo falló, detente y repórtalo.

8. **Rescata lo que quede en la partición Ubuntu** antes de borrarla. Está sin
   montar; se monta desde WSL2 o arrancando en ella. Revisa al menos:
   `~/.config/ngrok/`, cualquier `.env` o credencial, y `/etc/systemd/system/zero-*`.
   Compara contra lo que ya está en `/mnt/c/zeroai-respaldo-*` y copia lo que falte.

9. **El orden importa — hacerlo al revés deja el PC sin arrancar.** El equipo
   arranca hoy con GRUB (instalado por Ubuntu). Si borras la partición sin
   restaurar antes el gestor de arranque de Windows, queda "no bootable device".

   Secuencia correcta:
   a. Desde Windows, restaurar el Boot Manager: `bcdboot C:\Windows /s S: /f UEFI`
      (o el equivalente según la letra de la partición EFI).
   b. Reiniciar y **confirmar que arranca directo a Windows** sin pasar por GRUB.
   c. Recién ahí: Administración de discos → eliminar la partición ext4 (211 GB)
      y la partición de arranque de Linux si quedó.
   d. Extender la partición de Windows para absorber el espacio libre.
   e. Opcional: limpiar la entrada de GRUB de la partición EFI.

   **Este paso lo ejecuta Diego, no tú** — requiere reinicios y decisiones sobre
   el disco. Tu rol es guiarlo y confirmar cada paso antes del siguiente.

## REPORTE

- ¿Los 4 servicios activos? ¿El túnel público responde?
- ¿El webhook aceptó la firma válida y rechazó la inválida?
- ¿Llegó y se respondió un WhatsApp real? ¿En cuántos segundos?
- ¿Qué rescataste de la partición antes de borrarla?
- Si algo no pasó, **dilo claramente** en vez de darlo por bueno.
