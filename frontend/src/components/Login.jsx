import { useState } from 'react'
import { api } from '../lib/api'
import { Card, Button, Input } from './ui'

function Mark() {
  return (
    <svg width="40" height="40" viewBox="0 0 48 48" className="shrink-0">
      <rect width="48" height="48" rx="12" fill="#173d33" />
      <ellipse cx="24" cy="24" rx="8.5" ry="12.5" fill="none" stroke="#f4efe3" strokeWidth="4" />
      <line x1="16.5" y1="33" x2="31.5" y2="15" stroke="#f4efe3" strokeWidth="4" strokeLinecap="round" />
    </svg>
  )
}

export default function Login({ onSuccess }) {
  const [pw, setPw] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setErr('')
    try { await api.login(pw); onSuccess() }
    catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="min-h-screen grid place-items-center bg-[radial-gradient(120%_120%_at_100%_0%,#f4f7f5_0%,#fafafa_45%,#f7f8fa_100%)] p-4">
      <Card className="p-8 w-full max-w-sm">
        <div className="flex items-center gap-3 mb-1">
          <Mark />
          <div className="font-extrabold text-xl">
            <span style={{ color: '#173d33' }}>Zero</span><span style={{ color: '#2f8f78' }}>AI</span>
          </div>
        </div>
        <div className="text-sm text-zinc-500 mb-5">Ingresa tu contraseña de agencia.</div>
        <form onSubmit={submit} className="space-y-3">
          <Input type="password" autoFocus value={pw} onChange={(e) => setPw(e.target.value)} placeholder="Contraseña" className="w-full" />
          {err && <div className="text-sm text-rose-600">{err}</div>}
          <Button variant="accent" type="submit" disabled={busy} className="w-full">
            {busy ? 'Entrando…' : 'Entrar'}
          </Button>
        </form>
      </Card>
    </div>
  )
}
