import { useCallback, useSyncExternalStore } from 'react'

// El id interno del cliente es la llave (URLs, queries, storage); esto solo
// cambia el texto que ve el usuario. Sin etiqueta, se muestra el id tal cual.
let labels = {}
const listeners = new Set()

export function setClientLabels(next) {
  const clean = next && typeof next === 'object' && !Array.isArray(next) ? next : {}
  const same = Object.keys(clean).length === Object.keys(labels).length
    && Object.keys(clean).every((k) => labels[k] === clean[k])
  if (same) return
  labels = clean
  listeners.forEach((fn) => fn())
}

export function clientLabel(id) {
  if (!id) return id
  return labels[id] ?? id
}

const subscribe = (fn) => { listeners.add(fn); return () => listeners.delete(fn) }

// Suscribe al componente: se vuelve a pintar cuando llegan las etiquetas. La
// función cambia de identidad cuando cambian las etiquetas, así sirve como
// dependencia de useMemo/useEffect.
export function useClientLabel() {
  const snapshot = useSyncExternalStore(subscribe, () => labels)
  return useCallback((id) => (id ? snapshot[id] ?? id : id), [snapshot])
}
