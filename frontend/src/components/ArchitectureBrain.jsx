import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion, useReducedMotion } from 'framer-motion'
import { Activity, BrainCircuit, Cpu, Radio, Pause, Play, ArrowUpRight, ArrowRight, ShieldCheck, RefreshCw } from 'lucide-react'
import { api } from '../lib/api'
import { AGENTS, PIPELINE, TECHNOLOGIES, BRAND_MARKS, duration, statusLabel, engineLabel, timeAgo } from './architecture-data'
import './architecture-brain.css'

function TechnologyBadge({ name }) {
  const brand = BRAND_MARKS[name]
  return <span className={`brain-tech-badge ${brand ? 'has-brand' : ''}`} style={brand ? { '--tech-color': brand[1] } : undefined}>
    {brand && <span className="brain-tech-logo" style={{ '--tech-icon': `url(/technology/${brand[0]}.svg)` }} aria-hidden="true" />}{name}
  </span>
}

function SectionHeading({ number, title, detail }) {
  return <div className="brain-section-heading"><div><span>{number}</span><h3>{title}</h3></div><p>{detail}</p></div>
}

export default function ArchitectureBrain() {
  const [selected, setSelected] = useState('CONCIERGE')
  const [now, setNow] = useState(Date.now())
  const [animated, setAnimated] = useState(true)
  const [filter, setFilter] = useState('all')
  const [expanded, setExpanded] = useState(false)
  const reduced = useReducedMotion()
  const q = useQuery({ queryKey: ['agents-telemetry'], queryFn: () => api.agentsTelemetry(40), refetchInterval: 5000, refetchIntervalInBackground: false })
  useEffect(() => {
    const timer = setInterval(() => { if (!document.hidden) setNow(Date.now()) }, 1000)
    return () => clearInterval(timer)
  }, [])
  const { agentes = [], recientes = [], eventos = 0, max_eventos = 200 } = q.data || {}
  const { statsByAgent, latestByAgent, engines } = useMemo(() => {
    const statsByAgent = new Map(), latestByAgent = new Map(), engines = new Set()
    for (const entry of q.data?.agentes || []) {
      statsByAgent.set(entry.agent, entry)
      for (const engine of entry.engines || []) engines.add(engine)
    }
    for (const entry of q.data?.recientes || []) if (!latestByAgent.has(entry.agent)) latestByAgent.set(entry.agent, entry)
    return { statsByAgent, latestByAgent, engines: [...engines] }
  }, [q.data])
  const fresh = recientes.filter(e => now / 1000 - e.ts >= 0 && now / 1000 - e.ts < 12 && !q.isError)
  const active = new Set(fresh.map(e => e.agent))
  const agent = AGENTS.find(a => a.name === selected)
  const stats = statsByAgent.get(selected)
  const latest = latestByAgent.get(selected)
  const filtered = recientes.filter(e => filter === 'all' || (filter === 'errors' ? e.status === 'error' : e.agent === selected))
  const observed = AGENTS.filter(a => statsByAgent.has(a.name)).length
  const select = name => { setSelected(name); setExpanded(false) }
  const maxRuns = Math.max(1, ...agentes.map(a => a.corridas))

  return (
    <section className={`architecture-brain ${!animated || reduced ? 'brain-motion-paused' : ''}`} aria-label="Arquitectura de ZEROAI">
      <header className="brain-header">
        <div><div className="brain-brand"><img src="/logo-mark.png" width="30" height="30" alt="" /><span>ZERO<span className="brain-brand-ai">AI</span></span><i /> ARQUITECTURA</div><h2>Inteligencia que trabaja en equipo<span>.</span></h2><p>Explora cómo se conectan los agentes, sus motores y tu operación.</p></div>
        <div className="brain-header-actions"><div className={`brain-connection ${q.isError ? 'is-error' : ''}`} role="status"><Radio size={14} />{q.isLoading ? 'Conectando' : q.isError ? 'Sin conexión' : 'Telemetría conectada'}</div><button className="brain-control" onClick={() => setAnimated(v => !v)} aria-pressed={!animated} disabled={!!reduced}>{animated && !reduced ? <Pause size={13} /> : <Play size={13} />}{reduced ? 'Movimiento reducido' : animated ? 'Pausar animación' : 'Activar animación'}</button></div>
      </header>
      <div className="brain-metrics">
        <div><span>Ejecuciones registradas</span><strong>{q.data ? eventos : '—'}</strong><small>Ventana de {max_eventos} registros</small></div>
        <div><span>Agentes del mapa con actividad</span><strong>{q.data ? observed : '—'}<small> / 6</small></strong><small>Especialistas coordinados por ZERO</small></div>
        <div><span>Motores reportados</span><strong>{q.data ? engines.length : '—'}</strong><small>{engines.length ? engines.map(engineLabel).join(' · ') : 'Aparecen con la primera ejecución'}</small></div>
        <div><span>Estado de la actividad</span><strong className="brain-metric-state"><span className={`brain-dot ${fresh.length ? 'is-active' : ''}`} />{q.isError ? 'Desconectado' : fresh.length ? 'Actividad reciente' : q.isLoading ? 'Conectando…' : 'En espera'}</strong><small>{q.dataUpdatedAt ? `Datos actualizados ${timeAgo(q.dataUpdatedAt / 1000, now)}` : 'Consulta automática cada 5 segundos'}</small></div>
      </div>
      {q.isError && <div className="brain-error" role="alert">No se pudo actualizar la actividad. {q.data && 'Se conservan los últimos datos recibidos.'} <button onClick={() => q.refetch()}>Reintentar</button></div>}
      <div className="brain-workspace">
        <div className="brain-map-wrap">
          <div className="brain-map-label"><span>01 / EL CEREBRO</span><span>Selecciona un agente <ArrowUpRight size={12} /></span></div>
          <div className="brain-map">
            <svg className="brain-wires" viewBox="0 0 1000 600" preserveAspectRatio="none" aria-hidden="true">
              {AGENTS.map(a => {
                const path = `M 500 300 Q ${a.x * 10} 300 ${a.x * 10} ${a.y * 6}`
                return <g key={a.name} className={`${selected === a.name ? 'is-selected' : ''} ${active.has(a.name) ? 'is-active' : ''}`}><path d={path} className="brain-wire" /><path d={path} className="brain-signal" /></g>
              })}
            </svg>
            <div className={`brain-core ${fresh.length ? 'is-active' : ''}`}><div className="brain-orbit" /><div className="brain-orbit second" /><strong>ZERO</strong><span>ORQUESTADOR</span></div>
            {AGENTS.map(({ name, label, role, icon: Icon, x, y }) => {
              const entry = latestByAgent.get(name)
              return <button key={name} className={`brain-node ${selected === name ? 'is-selected' : ''} ${active.has(name) ? 'is-active' : ''}`} style={{ '--x': `${x}%`, '--y': `${y}%` }} onClick={() => select(name)} aria-pressed={selected === name} aria-label={`${label}: ${role}`}>
                <span className="brain-node-top"><span className="brain-node-icon"><Icon size={17} /></span><span className="brain-node-count">{statsByAgent.get(name)?.corridas ?? 0} <Activity size={10} /></span></span><strong>{label}</strong><span className="brain-node-history-label">Última ejecución</span><span className="brain-node-engine" title={entry ? `Motor de la última ejecución: ${engineLabel(entry.engine)} · ${timeAgo(entry.ts, now)}` : 'Sin ejecución en el historial consultado'}>{entry ? engineLabel(entry.engine) : 'Sin registro reciente'}</span><small>{active.has(name) ? '● Ejecución recibida' : entry ? timeAgo(entry.ts, now) : 'Explorar agente ↗'}</small>
              </button>
            })}
          </div>
          <div className="brain-legend"><span><i /> Conexión del sistema</span><span><i className="gold" /> Selección</span><span><i className="live" /> Resultado recibido &lt; 12 s</span></div>
        </div>
        <aside className="brain-detail" aria-label="Detalle del agente seleccionado">
          <div className="brain-eyebrow">DENTRO DEL AGENTE</div>
          <motion.div key={selected} initial={{ opacity: 0, y: reduced ? 0 : 5 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .18 }}>
            <div className="brain-detail-title"><agent.icon size={23} /><h3>{agent.label}</h3></div><p>{agent.role}</p>
            <div className="brain-route-label">Ruta de referencia</div><div className="brain-route"><span><Cpu size={14} /> ZERO asigna la tarea</span><b>↓</b><span>{agent.label} procesa</span><b>↕</b><span><BrainCircuit size={14} /> Motor según la tarea</span></div>
            <div className="brain-engine-context"><div><span>Motor de la última ejecución</span><strong>{latest ? engineLabel(latest.engine) : 'Sin registro reciente'}</strong></div><div><span>Motor configurado actualmente</span><strong>No informado por la telemetría</strong></div><p>Un registro simulado no indica que el agente esté configurado en mock hoy.</p></div>
            <dl><div><dt>Ejecuciones</dt><dd>{q.isLoading ? '—' : stats?.corridas ?? 0}</dd></div><div><dt>Duración típica</dt><dd>{stats ? duration(stats.ms_mediana) : '—'}</dd></div><div><dt>Errores</dt><dd>{q.isLoading ? '—' : stats?.errores ?? 0}</dd></div><div><dt>Último resultado</dt><dd className={latest?.status === 'error' ? 'brain-text-error' : ''}>{statusLabel(latest?.status)}</dd></div></dl>
            <div className="brain-detail-note">{latest ? <>{timeAgo(latest.ts, now)} · {duration(latest.ms)}<div className="brain-io"><span><b>{(latest.in_chars ?? 0).toLocaleString('es-CL')}</b> caracteres de entrada</span><ArrowRight size={13} /><span><b>{(latest.out_chars ?? 0).toLocaleString('es-CL')}</b> caracteres de salida</span></div></> : 'Sin ejecuciones de este agente en los últimos registros disponibles.'}</div>
          </motion.div>
        </aside>
      </div>

      <div className="brain-section brain-pipeline-section">
        <SectionHeading number="02" title="De oportunidad a resultado" detail="Recorre las etapas para explorar quién interviene." />
        <div className="brain-pipeline">{PIPELINE.map(([label, name, description], i) => <div key={label} className={`brain-step ${name === selected ? 'is-selected' : ''}`}>
          {name ? <button onClick={() => select(name)} aria-pressed={name === selected}><span className="brain-step-number">{String(i + 1).padStart(2, '0')}</span><strong>{label}</strong><small>{name.charAt(0) + name.slice(1).toLowerCase()}</small></button> : <div title={description}><span className="brain-step-number"><ShieldCheck size={16} /></span><strong>{label}</strong><small>Control de ZERO</small></div>}
        </div>)}</div>
        <p className="brain-caption">Ruta de referencia: cada ejecución sigue los pasos que requiere su tarea. Validar es una decisión del orquestador.</p>
      </div>

      <div className="brain-section">
        <SectionHeading number="03" title="La tecnología detrás de cada decisión" detail="Componentes del sistema y su función. Su disponibilidad depende de la configuración." />
        <div className="brain-tech-grid">{TECHNOLOGIES.map(({ title, icon: Icon, tags, text, note }) => <article className="brain-tech" key={title}><div className="brain-tech-title"><span><Icon size={19} /></span><h4>{title}</h4></div><div className="brain-tech-tags">{tags.map(tag => <TechnologyBadge key={tag} name={tag} />)}</div><p>{text}</p><small>{note}</small></article>)}</div>
      </div>

      <div className="brain-section brain-observability">
        <SectionHeading number="04" title="Pulso de la operación" detail="Resultados reales, sin contenido de conversaciones." />
        <div className="brain-activity-layout"><aside className="brain-distribution"><h4>Trabajo por agente</h4><p>Distribución de las últimas {eventos} ejecuciones</p>{agentes.length ? agentes.map(a => <div className="brain-distribution-row" key={a.agent}><div><span>{a.agent}</span><b>{a.corridas}</b></div><div className="brain-bar"><span style={{ width: `${a.corridas / maxRuns * 100}%` }} /></div></div>) : <p>{q.isLoading ? 'Cargando métricas…' : 'Sin registros disponibles'}</p>}</aside>
          <div className="brain-feed"><div className="brain-feed-heading"><label htmlFor="brain-event-filter">Ejecuciones <span>({filtered.length})</span></label><select id="brain-event-filter" value={filter} onChange={e => { setFilter(e.target.value); setExpanded(false) }}><option value="all">Todos los agentes</option><option value="selected">Solo {agent.label}</option><option value="errors">Solo errores</option></select><button className="brain-control brain-refresh" onClick={() => q.refetch()} disabled={q.isFetching} aria-label="Actualizar actividad"><RefreshCw size={14} /></button></div>
            {q.isLoading ? <p className="brain-empty">Cargando actividad…</p> : !filtered.length ? <div className="brain-empty"><Activity size={24} /><p>{q.isError ? 'La actividad no está disponible. Reintenta la conexión.' : recientes.length ? 'No hay ejecuciones que coincidan con este filtro.' : 'Esperando la primera ejecución. El mapa se iluminará al recibir resultados.'}</p></div> : <div className="brain-event-list">{filtered.slice(0, expanded ? 40 : 6).map((e, i) => <button className="brain-event" key={`${e.task_id}-${e.ts}-${i}`} onClick={() => { if (AGENTS.some(a => a.name === e.agent)) setSelected(e.agent) }}><span className={`brain-event-status ${e.status}`}>{statusLabel(e.status)}</span><span className="brain-event-identity"><strong>{e.agent}</strong><span title={e.engine}>{engineLabel(e.engine)}</span></span><span className="brain-event-timing">{duration(e.ms)}<time dateTime={new Date(e.ts * 1000).toISOString()}>{timeAgo(e.ts, now)}</time></span></button>)}</div>}
            {filtered.length > 6 && <button className="brain-show-more" onClick={() => setExpanded(v => !v)}>{expanded ? 'Ver menos' : `Ver las ${filtered.length} ejecuciones`} <ArrowUpRight size={13} /></button>}
          </div>
        </div>
      </div>
      <footer className="brain-footer"><img src="/logo-mark.png" width="22" height="22" alt="" /><p>Los pulsos representan ejecuciones finalizadas, no llamadas en curso. Los motores son los reportados por el backend; el registro no distingue todos los cambios a un motor de respaldo. Mock indica una simulación.</p><span>ZEROAI / ARQUITECTURA</span></footer>
    </section>
  )
}
