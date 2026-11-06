import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { ConvSummary, User } from '../api'
import { Icon } from '../icons'
import { useTheme } from '../theme'

interface Props {
  user: User
  convs: ConvSummary[]
  activeId: number | null
  onNew: () => void
  onSelect: (id: number) => void
  onRename: (id: number, title: string) => void
  onDelete: (id: number) => void
  onLogout: () => void
  open: boolean
}

export function Sidebar({ user, convs, activeId, onNew, onSelect, onRename, onDelete, onLogout, open }: Props) {
  const { theme, toggle } = useTheme()
  const [editing, setEditing] = useState<number | null>(null)
  const [draft, setDraft] = useState('')

  return (
    <aside className={`sidebar${open ? ' open' : ''}`}>
      <div className="brand"><img src="/favicon.svg" alt="" width={22} height={22} />CodingApp</div>
      <button className="btn primary block" onClick={onNew}><Icon name="plus" size={15} />New chat</button>
      <nav className="conv-list">
        {convs.length === 0 && <div className="muted small pad">No conversations yet</div>}
        {convs.map((c) => (
          <div key={c.id} className={`conv${c.id === activeId ? ' active' : ''}`} onClick={() => onSelect(c.id)}>
            {editing === c.id ? (
              <input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} onClick={(e) => e.stopPropagation()}
                onBlur={() => { setEditing(null); if (draft.trim()) onRename(c.id, draft.trim()) }}
                onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); if (e.key === 'Escape') setEditing(null) }} />
            ) : (
              <span className="conv-title" title={c.title}>{c.title}</span>
            )}
            <span className="conv-actions">
              <button className="icon-btn" title="Rename" onClick={(e) => { e.stopPropagation(); setDraft(c.title); setEditing(c.id) }}>
                <Icon name="edit" size={13} /></button>
              <button className="icon-btn" title="Delete" onClick={(e) => {
                e.stopPropagation()
                if (confirm(`Delete "${c.title}"? This removes its messages and files.`)) onDelete(c.id)
              }}><Icon name="trash" size={13} /></button>
            </span>
          </div>
        ))}
      </nav>
      <div className="sidebar-foot">
        <div className="who" title={user.email || user.username}>
          <div className="avatar-sm">{(user.display_name || user.username).slice(0, 1).toUpperCase()}</div>
          <div className="who-text">
            <div className="ellipsis">{user.display_name || user.username}</div>
            <div className="muted small">{user.source === 'ldap' ? 'Active Directory' : 'Local'}{user.is_admin ? ' · Admin' : ''}</div>
          </div>
        </div>
        <div className="row gap-xs">
          {user.is_admin && <Link className="icon-btn" to="/admin" title="Administration"><Icon name="settings" size={16} /></Link>}
          <button className="icon-btn" onClick={toggle} title="Toggle theme"><Icon name={theme === 'dark' ? 'sun' : 'moon'} size={16} /></button>
          <button className="icon-btn" onClick={onLogout} title="Sign out"><Icon name="logout" size={16} /></button>
        </div>
      </div>
    </aside>
  )
}
