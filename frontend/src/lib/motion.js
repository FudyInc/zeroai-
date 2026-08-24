/* El lenguaje de movimiento del dashboard — una sola fuente.
 *
 * Antes cada página redefinía sus propias variantes con valores parecidos pero
 * distintos: la curva [0.22, 1, 0.36, 1] estaba copiada a mano en cuatro archivos, los
 * stagger iban de 0.06 a 0.08 sin criterio, y siete páginas no tenían movimiento
 * alguno. El resultado no es "poco animado", es *inconsistente*: la app se siente
 * distinta según dónde estés parado, que es exactamente lo contrario de sofisticado.
 *
 * Dos ideas sostienen esto:
 *
 * 1. **El movimiento es jerarquía, no decoración.** Lo que importa entra con más
 *    recorrido y algo más lento (`rise`); lo secundario apenas se insinúa (`fade`).
 *    Si todo entra igual, el movimiento no comunica nada y solo cuesta tiempo.
 *
 * 2. **Nada dura más que la paciencia.** Ninguna entrada pasa de ~380 ms: sobre eso
 *    el usuario deja de leerlo como respuesta del sistema y empieza a esperar.
 *
 * La curva EDITORIAL es una salida exponencial: arranca rápido y frena largo. Da la
 * sensación de peso y control, en vez del rebote elástico que se ha vuelto el default
 * de cualquier plantilla.
 */

/* Salida exponencial. La curva de la casa: úsala salvo que haya una razón. */
export const EDITORIAL = [0.22, 1, 0.36, 1]

/* Entrada con cuerpo, para superficies que se posan (tarjetas, modales). Amortiguado
   a propósito para que no rebote: el rebote es simpático una vez y molesto siempre. */
export const SPRING = { type: 'spring', stiffness: 320, damping: 28, mass: 0.9 }

export const DURATION = {
  micro: 0.15,   // respuesta al puntero: tiene que sentirse instantánea
  base: 0.28,    // entradas normales
  slow: 0.38,    // el elemento principal de una vista
}

/* ¿El sistema pide menos movimiento? No es un detalle de accesibilidad opcional: para
   alguien con sensibilidad vestibular una interfaz que se desplaza sin permiso marea de
   verdad. Se respeta acortando el recorrido, nunca quitando el cambio de opacidad
   (sin él, los elementos aparecerían de golpe y se perdería la noción de qué cambió). */
export const prefersReducedMotion = () =>
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

const y = (px) => (prefersReducedMotion() ? 0 : px)

/* --- Variantes ------------------------------------------------------------------ */

/* Lo secundario: se insinúa y ya. */
export const fade = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { duration: DURATION.base, ease: EDITORIAL } },
}

/* Lo importante: sube con recorrido visible. */
export const rise = {
  hidden: { opacity: 0, y: y(14) },
  show: { opacity: 1, y: 0, transition: { duration: DURATION.slow, ease: EDITORIAL } },
}

/* Superficies que se posan: tarjetas de una grilla, tiles de métrica. */
export const surface = {
  hidden: { opacity: 0, y: y(12), scale: prefersReducedMotion() ? 1 : 0.985 },
  show: { opacity: 1, y: 0, scale: 1, transition: SPRING },
}

/* Contenedor con cascada. `stagger` en segundos entre hijos: 0.05 se lee como un
   grupo que aparece ordenado; sobre 0.12 se lee como lentitud. */
export const stagger = (delay = 0.05, initialDelay = 0) => ({
  hidden: {},
  show: { transition: { staggerChildren: prefersReducedMotion() ? 0 : delay,
                        delayChildren: initialDelay } },
})

/* Cambio de página. Sale hacia arriba y entra desde abajo: da dirección al cambio en
   vez de un parpadeo sin sentido de continuidad. */
export const page = {
  initial: { opacity: 0, y: y(10) },
  animate: { opacity: 1, y: 0, transition: { duration: DURATION.base, ease: EDITORIAL } },
  exit: { opacity: 0, y: y(-8), transition: { duration: DURATION.micro, ease: EDITORIAL } },
}

/* Crossfade entre esqueleto y contenido. Hoy el salto es seco: el esqueleto desaparece
   y el contenido aparece de golpe, lo que hace que una carga rápida se lea como un
   parpadeo defectuoso. */
export const swap = {
  initial: { opacity: 0 },
  animate: { opacity: 1, transition: { duration: DURATION.base, ease: EDITORIAL } },
  exit: { opacity: 0, transition: { duration: DURATION.micro, ease: EDITORIAL } },
}

/* Respuesta al puntero para superficies pulsables. Sutil a propósito — se siente más
   que se ve; un lift de 4px ya se lee como globo. */
export const hoverLift = prefersReducedMotion()
  ? {}
  : { whileHover: { y: -2, transition: { duration: DURATION.micro, ease: EDITORIAL } },
      whileTap: { scale: 0.99 } }
