import { Search, ShieldCheck, Send, Repeat2, ChartNoAxesCombined, MessagesSquare, BrainCircuit, Database, Cpu, Monitor, Network, Megaphone, Globe, Mail, MessageCircle, PhoneCall, Linkedin, Instagram, Facebook, FileSpreadsheet } from 'lucide-react'

// `channels` refleja SOLO integraciones reales del código (nunca decorativo):
// Prospector -> discovery.py (DuckDuckGo); Outreach/Tracker -> config.py
// TIERS[].channels + zero/channels.py (email/whatsapp reales, cold_call vía
// Vapi, linkedin redactado y entregado a mano); Concierge -> su propio
// docstring (solo atiende email/whatsapp); Analyst -> sheets.py (sync real a
// Google Sheets); MediaBuyer -> Meta Ads (Instagram/Facebook). Qualifier no
// tiene canal: es scoring interno, sin integración externa.
const OUTREACH_CHANNELS = [
  { icon: Mail, color: '#EA4335', label: 'Email (SMTP)' },
  { icon: MessageCircle, color: '#25D366', label: 'WhatsApp' },
  { icon: PhoneCall, color: 'var(--color-gold-deep)', label: 'Llamada en frío (Vapi)' },
  { icon: Linkedin, color: '#0A66C2', label: 'LinkedIn (redactado, entrega manual)' },
]

export const AGENTS = [
  { name: 'PROSPECTOR', label: 'Prospector', role: 'Descubre y enriquece leads', icon: Search, x: 50, y: 11.4,
    channels: [{ icon: Globe, color: '#DE5833', label: 'Búsqueda web (DuckDuckGo)' }] },
  { name: 'QUALIFIER', label: 'Qualifier', role: 'Evalúa el encaje con tu ICP', icon: ShieldCheck, x: 80.6, y: 26 },
  { name: 'OUTREACH', label: 'Outreach', role: 'Prepara el primer contacto', icon: Send, x: 88.2, y: 58.6, channels: OUTREACH_CHANNELS },
  { name: 'TRACKER', label: 'Tracker', role: 'Da seguimiento a cada oportunidad', icon: Repeat2, x: 67, y: 84.8, channels: OUTREACH_CHANNELS },
  { name: 'CONCIERGE', label: 'Concierge', role: 'Responde y agenda reuniones', icon: MessagesSquare, x: 33, y: 84.8,
    channels: [
      { icon: Mail, color: '#EA4335', label: 'Email (SMTP)' },
      { icon: MessageCircle, color: '#25D366', label: 'WhatsApp' },
    ] },
  { name: 'ANALYST', label: 'Analyst', role: 'Analiza y proyecta resultados', icon: ChartNoAxesCombined, x: 11.8, y: 58.6,
    channels: [{ icon: FileSpreadsheet, color: '#0F9D58', label: 'Google Sheets (sync)' }] },
  { name: 'MEDIABUYER', label: 'MediaBuyer', role: 'Optimiza campañas de Meta Ads', icon: Megaphone, x: 19.4, y: 26,
    channels: [
      { icon: Instagram, color: '#C13584', label: 'Instagram Ads (Meta)' },
      { icon: Facebook, color: '#1877F2', label: 'Facebook Ads (Meta)' },
    ] },
]

export const PIPELINE = [
  ['Descubrir', 'PROSPECTOR', 'Encuentra oportunidades'],
  ['Calificar', 'QUALIFIER', 'Prioriza por encaje'],
  ['Validar', null, 'ZERO revisa antes de enviar'],
  ['Contactar', 'OUTREACH', 'Prepara el mensaje'],
  ['Dar seguimiento', 'TRACKER', 'Retoma la conversación'],
  ['Responder', 'CONCIERGE', 'Resuelve y agenda'],
  ['Proyectar', 'ANALYST', 'Estima resultados'],
]

// Capabilities confirmed in the repository, not health checks for deployed services.
export const TECHNOLOGIES = [
  { title: 'Orquestación', icon: Cpu, tags: ['Python', 'FastAPI', 'JSON'], text: 'ZERO asigna tareas, valida respuestas y coordina el trabajo de los agentes.', note: 'Lógica de control · no es un LLM' },
  { title: 'Inferencia', icon: BrainCircuit, tags: ['Ollama · qwen2.5', 'Anthropic', 'OpenAI'], text: 'Backends intercambiables para ejecutar los mismos agentes. Hoy corre en local con qwen2.5:14b; Anthropic y OpenAI se activan con su API key.', note: 'Sin motor real el backend responde 503 — ya no simula' },
  { title: 'Memoria y datos', icon: Database, tags: ['Supabase', 'CRM', 'ICP'], text: 'Conserva leads, contexto y criterios de calificación. También admite persistencia local.', note: 'La persistencia depende de la configuración' },
  { title: 'Comunicación', icon: MessagesSquare, tags: ['WhatsApp', 'SMTP', 'Twilio'], text: 'Los agentes preparan las respuestas y la capa de canales gestiona su envío.', note: 'Envíos reales sujetos a configuración' },
  { title: 'Interfaz', icon: Monitor, tags: ['React', 'Vite', 'Framer Motion'], text: 'Una vista interactiva para explorar agentes, seguir resultados y recorrer el pipeline.', note: 'Adaptable a móvil · movimiento reducido' },
  { title: 'Observabilidad', icon: Network, tags: ['TanStack Query', 'Telemetría'], text: 'Consulta ejecuciones finalizadas, tiempos, estados y volumen de entrada y salida.', note: 'Actualización cada 5 s mientras la vista está activa' },
]

export const duration = ms => ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms || 0)} ms`
export const statusLabel = value => ({ done: 'Completado', error: 'Error', partial: 'Parcial' }[value] || value || 'Sin registro')
// `mock` sigue traducido a propósito: el historial guarda corridas viejas, de cuando el
// mock era un motor legítimo (hasta el 2026-09-08). Que se vea marcado como simulación es
// justamente el punto — no se borra el pasado, se etiqueta.
export const engineLabel = engine => engine === 'mock' ? 'Mock · simulación' : engine === 'AnthropicBackend' ? 'Anthropic' : engine === 'OpenAIBackend' ? 'OpenAI' : engine === 'LocalBackend' ? 'Local · Ollama' : engine || 'Sin motor registrado'
export function timeAgo(ts, now) {
  const seconds = Math.max(0, Math.floor(now / 1000 - ts))
  return seconds < 60 ? `hace ${seconds} s` : seconds < 3600 ? `hace ${Math.floor(seconds / 60)} min` : seconds < 86400 ? `hace ${Math.floor(seconds / 3600)} h` : `hace ${Math.floor(seconds / 86400)} d`
}

export const BRAND_MARKS = {
  Python: ['python', '#3776AB'], FastAPI: ['fastapi', '#009688'], JSON: ['json', '#555555'],
  Ollama: ['ollama', '#222222'], Anthropic: ['anthropic', '#191919'], Supabase: ['supabase', '#3ECF8E'],
  WhatsApp: ['whatsapp', '#25D366'], Twilio: ['twilio', '#F22F46'], React: ['react', '#61DAFB'],
  Vite: ['vite', '#646CFF'], 'Framer Motion': ['framer', '#0055FF'], 'TanStack Query': ['reactquery', '#FF4154'],
}
