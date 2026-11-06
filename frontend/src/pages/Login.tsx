import { useState, type FormEvent } from 'react'
import { api, type User } from '../api'

export function LoginPage({ onLogin }: { onLogin: (u: User) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      onLogin(await api.login(username.trim(), password))
    } catch (err: any) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <form className="login card" onSubmit={submit}>
        <div className="brand lg"><img src="/favicon.svg" alt="" width={34} height={34} />CodingApp</div>
        <p className="muted small">Sign in with your domain account</p>
        <label>Username
          <input autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="username" />
        </label>
        <label>Password
          <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <div className="notice danger">{error}</div>}
        <button className="btn primary block" disabled={busy || !username || !password}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
    </div>
  )
}
