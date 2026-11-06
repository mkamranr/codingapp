import { useEffect, useState } from 'react'
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { api, onUnauthorized, type User } from './api'
import { AdminPage } from './pages/Admin'
import { ChatPage } from './pages/Chat'
import { LoginPage } from './pages/Login'

export default function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined)
  const navigate = useNavigate()

  useEffect(() => {
    onUnauthorized(() => setUser(null))
    api.me().then(setUser).catch(() => setUser(null))
  }, [])

  if (user === undefined) return <div className="splash">Loading…</div>
  if (user === null) return <LoginPage onLogin={(u) => { setUser(u); navigate('/') }} />

  const logout = async () => {
    await api.logout().catch(() => {})
    setUser(null)
  }

  return (
    <Routes>
      <Route path="/" element={<ChatPage user={user} onLogout={logout} />} />
      <Route path="/c/:id" element={<ChatPage user={user} onLogout={logout} />} />
      <Route path="/admin" element={user.is_admin ? <AdminPage /> : <Navigate to="/" />} />
      <Route path="*" element={<Navigate to="/" />} />
    </Routes>
  )
}
