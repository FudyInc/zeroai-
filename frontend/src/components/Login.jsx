import { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { api } from '../lib/api'
import { Card, Button, Input } from './ui'

function Mark() {
  return (
    <img src="/logo-mark.png" alt="ZeroAI" width="40" height="40" className="shrink-0" />
  )
}

function GoogleMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84c-.21 1.13-.84 2.09-1.8 2.73v2.27h2.92c1.7-1.57 2.68-3.88 2.68-6.64z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.81 5.96-2.18l-2.92-2.27c-.81.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.71H.96v2.34C2.44 15.98 5.48 18 9 18z" />
      <path fill="#FBBC05" d="M3.97 10.7c-.18-.54-.28-1.11-.28-1.7s.1-1.16.28-1.7V4.96H.96A8.996 8.996 0 000 9c0 1.45.35 2.83.96 4.04l3.01-2.34z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.51.45 3.44 1.35l2.59-2.59C13.46.89 11.43 0 9 0 5.48 0 2.44 2.02.96 4.96l3.01 2.34C4.68 5.16 6.66 3.58 9 3.58z" />
    </svg>
  )
}

export default function Login({ onSuccess }) {
  const [user, setUser] = useState('')
  const [pw, setPw] = useState('')
  const [show, setShow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [busyGoogle, setBusyGoogle] = useState(false)
  const [err, setErr] = useState('')

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setErr('')
    try { await api.login(user, pw); onSuccess() }
    catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  const submitGoogle = async () => {
    setBusyGoogle(true); setErr('')
    try {
      const { error } = await api.signInWithGoogle()
      if (error) throw error
      // Éxito: el navegador redirige a Google acá — no queda nada más por hacer.
    } catch (e) { setErr(e.message); setBusyGoogle(false) }
  }

  return (
    <div className="min-h-screen grid place-items-center bg-[radial-gradient(120%_120%_at_100%_0%,#f2f1ec_0%,#f4f4f4_45%,#f6f5f2_100%)] p-4">
      <Card className="p-8 w-full max-w-sm">
        <div className="flex items-center gap-3 mb-1">
          <Mark />
          <div className="font-display font-extrabold text-xl tracking-tight text-brand">
            ZEROAI
          </div>
        </div>
        <div className="text-sm text-zinc-500 mb-5">Ingresa con tu cuenta de Google, o con usuario y contraseña.</div>

        <button type="button" onClick={submitGoogle} disabled={busyGoogle}
          className="w-full inline-flex items-center justify-center gap-2.5 rounded-xl border border-zinc-200 bg-white px-4 py-2.5 text-sm font-medium text-zinc-700 shadow-sm transition-all hover:bg-zinc-50 active:scale-[.98] disabled:opacity-50 disabled:pointer-events-none">
          <GoogleMark /> {busyGoogle ? 'Redirigiendo…' : 'Continuar con Google'}
        </button>

        <div className="flex items-center gap-3 my-4">
          <div className="h-px flex-1 bg-zinc-100" />
          <span className="text-xs text-zinc-400">o</span>
          <div className="h-px flex-1 bg-zinc-100" />
        </div>

        <form onSubmit={submit} className="space-y-3">
          <Input value={user} onChange={(e) => setUser(e.target.value)} placeholder="Usuario" autoFocus className="w-full" />
          <div className="relative">
            <Input type={show ? 'text' : 'password'} value={pw} onChange={(e) => setPw(e.target.value)} placeholder="Contraseña" className="w-full pr-10" />
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
