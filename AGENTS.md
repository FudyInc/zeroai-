# Contexto del motor WhatsApp

Este repositorio contiene el código y la información comercial que usa el agente. Al trabajar aquí, mantén ambas al día.

## Antes de cambiar algo

- Lee `CLAUDE.md` para las reglas del producto y comprueba el comportamiento en el código actual. Las fechas y estados de los documentos antiguos pueden haber quedado atrás.
- Revisa `git status` y conserva los cambios que ya estén en curso.
- Para respuestas comerciales de ZeroAI, consulta `docs/ficha-zeroai.md` y el ICP de `scripts/cargar_empresa.py`. No completes hechos comerciales, precios, horarios o promesas con suposiciones.

## Al terminar un cambio

- Registra los pedidos, decisiones y cambios relevantes en `docs/registro-avances.json`
  durante la misma tarea. Indica fecha, origen, estado, evidencia y qué queda
  pendiente. El dashboard los muestra en **Avances**; no presentes una prueba local
  como despliegue en producción. No agregues secretos ni datos personales de leads.
- Actualiza en la misma tarea el documento o ficha afectada y señala la fecha de verificación. Si no se pudo comprobar un hecho, déjalo explícitamente pendiente; no lo presentes como vigente.
- La ficha versionada de ZeroAI es `docs/ficha-zeroai.md`. El agente responde con la ficha activa del almacén, que puede diferir del archivo. Antes de cargarla, compara ambos con `python3 scripts/verificar_ficha.py --empresa zeroai` y revisa cuál versión contiene los datos correctos. El script solo lee.
- Las ediciones hechas en el dashboard crean versiones en el almacén, pero no actualizan el archivo del repositorio. Si una edición del dashboard es la válida, incorpórala también a la ficha versionada. Si el archivo es la versión válida, usa el simulacro de `scripts/cargar_empresa.py` antes de aplicar una carga. No sobrescribas una ficha activa diferente sin revisar el contenido.
- Mantén el cuerpo entre `INICIO FICHA` y `FIN FICHA` dentro de 4000 caracteres: el orquestador corta el resto. Mantén los precios calculables en el catálogo y `quotes.py`, no en texto libre.
- Al informar el estado, distingue lo comprobado en código, lo comprobado en el almacén local y lo comprobado en producción.
