import './workspace.css'

/** Cabecera común para las vistas operativas del dashboard. */
export function WorkspaceHero({ eyebrow, title, description, icon: Icon, aside, children }) {
  return (
    <section className={'workspace-hero' + (aside ? '' : ' workspace-hero-single')} aria-labelledby="workspace-title">
      <div className="workspace-hero-main">
        <span className="workspace-hero-eyebrow">
          {Icon && <Icon size={14} aria-hidden="true" />}
          {eyebrow}
        </span>
        <h1 id="workspace-title">{title}</h1>
        <p>{description}</p>
        {children && <div className="workspace-hero-actions">{children}</div>}
      </div>
      {aside && (
        <div className="workspace-hero-aside">
          <span>{aside.label}</span>
          <strong>{aside.value}</strong>
          {aside.detail && <small>{aside.detail}</small>}
        </div>
      )}
    </section>
  )
}

export function WorkspaceSectionHeading({ eyebrow, title, description, children }) {
  return (
    <div className="workspace-section-heading">
      <div>
        {eyebrow && <span className="workspace-section-eyebrow">{eyebrow}</span>}
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {children && <div className="workspace-section-actions">{children}</div>}
    </div>
  )
}
