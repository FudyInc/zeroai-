import { useEffect } from 'react'

/* Comportamiento compartido de cualquier capa que se abre encima: cerrar con
   Escape y congelar el scroll del fondo mientras está abierta.

   Existe porque de los cinco modales del dashboard solo el buscador cerraba
   con Escape — y lo hacía en el onKeyDown de su input, así que ni siquiera
   funcionaba si el foco estaba en otra parte. El resto solo se cerraba
   clickeando el fondo o el botón, que con un teclado es un callejón sin salida.

   El scroll del fondo importa sobre todo en el teléfono: sin congelarlo, al
   deslizar dentro de un modal se mueve la página de atrás y al cerrar quedas
   en otro lugar del que estabas.

   Uso:  useDismiss(abierto, onClose)
*/

/* El bloqueo se lleva con un CONTADOR de capas abiertas, no guardando y
   restaurando el valor anterior. La versión con "guardar el valor previo"
   parecía más simple y estaba mal por dos motivos, ambos encontrados en vivo:

   1. `onClose` suele llegar como arrow function inline (`onClose={() =>
      setLeadKey(null)}`), así que cambia de identidad en cada render y el
      efecto se vuelve a suscribir. En la segunda suscripción el "valor previo"
      ya era 'hidden', y al cerrar restauraba 'hidden' — scroll muerto para
      siempre.
   2. Con dos capas encimadas, cerrar la de arriba restauraba el scroll aunque
      la de abajo siguiera abierta.

   Un contador es inmune a las dos cosas: solo la primera capa bloquea y solo
   la última desbloquea. */
let capasAbiertas = 0

export function useDismiss(open, onClose) {
  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') onClose?.() }
    document.addEventListener('keydown', onKey)
    capasAbiertas += 1
    if (capasAbiertas === 1) document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      capasAbiertas = Math.max(0, capasAbiertas - 1)
      if (capasAbiertas === 0) document.body.style.overflow = ''
    }
  }, [open, onClose])
}
