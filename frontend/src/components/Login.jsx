import { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { api } from '../lib/api'
import { Card, Button, Input } from './ui'

function Mark() {
  return (
    <img src="/logo.png" alt="ZeroAI" width="40" height="40" className="shrink-0" />
  )
}

export default function Login({ onSuccess }) {
  const [pw, setPw] = useState('')
  const [show, setShow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setErr('')
    try { await api.login(pw); onSuccess() }
    catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="min-h-screen grid place-items-center bg-[radial-gradient(120%_120%_at_100%_0%,#f2f1ec_0%,#f4f4f4_45%,#f6f5f2_100%)] p-4">
      <Card className="p-8 w-full max-w-sm">
        <div className="flex items-center gap-3 mb-1">
          <Mark />
          <div className="font-display font-extrabold text-xl tracking-tight">
            <span className="text-brand">ZERO</span><span className="text-gold">AI</span>
          </div>
        </div>
        <div className="text-sm text-zinc-500 mb-5">Ingresa tu contraseña de agencia.</div>
        <form onSubmit={submit} className="space-y-3">
          <div className="relative">
            <Input type={show ? 'text' : 'password'} autoFocus value={pw} onChange={(e) => setPw(e.target.value)} placeholder="Contraseña" className="w-full pr-10" />
            <button type="button" onClick={() => setShow((v) => !v)} aria-label={show ? 'Ocultar contraseña' : 'Mostrar contraseña'}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-600">
              {show ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
          {err && <div className="text-sm text-rose-600">{err}</div>}
          <Button variant="accent" type="submit" disabled={busy} className="w-full">
            {busy ? 'Entrando…' : 'Entrar'}
          </Button>
        </form>
      </Card>
    </div>
  )
}
