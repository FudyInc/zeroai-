/* Halo de gradiente animado detrás de un elemento (estilo "NoiseBackground").
   Úsalo SOLO en el CTA estrella — un acento, no en todos lados.

   <Glow><Button variant="accent">Enviar</Button></Glow>
*/
export function Glow({ children, className = '', radius = 'rounded-xl' }) {
  return (
    <span className={`relative inline-flex ${className}`}>
      <span aria-hidden className={`glow-halo absolute -inset-[2.5px] ${radius} blur-[5px] opacity-70`} />
      <span className="relative inline-flex">{children}</span>
    </span>
  )
}
