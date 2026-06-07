import { clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs) {
  return twMerge(clsx(inputs))
}

export const STAGES = {
  new: { l: 'Nuevos', c: '#64748b' },
  qualified: { l: 'Calificados', c: '#0284c7' },
  disqualified: { l: 'Descartados', c: '#e11d48' },
  contacted: { l: 'Contactados', c: '#d97706' },
  nurturing: { l: 'En seguimiento', c: '#db2777' },
  replied: { l: 'Respondieron', c: '#2563eb' },
  meeting: { l: 'Reunión', c: '#059669' },
  won: { l: 'Ganados', c: '#16a34a' },
  lost: { l: 'Perdidos', c: '#94a3b8' },
}
export const ORDER = ['new', 'qualified', 'disqualified', 'contacted', 'nurturing', 'replied', 'meeting', 'won', 'lost']

export const scoreColor = (s) => (s == null ? '#94a3b8' : s >= 80 ? '#16a34a' : s >= 70 ? '#d97706' : '#dc2626')
