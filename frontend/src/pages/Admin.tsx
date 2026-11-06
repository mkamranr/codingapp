import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Icon } from '../icons'
import { fmtTokens } from '../util'

type Tab = 'ldap' | 'llm' | 'users'

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="muted small">{hint}</span>}
    </label>
  )
}

function LdapTab() {
  const [cfg, setCfg] = useState<any>(null)
  const [password, setPassword] = useState('')
  const [testUser, setTestUser] = useState('')
  const [anon, setAnon] = useState(false)
  const [testPw, setTestPw] = useState('')
  const [msg, setMsg] = useState<{ kind: string; text: string } | null>(null)
  const [test, setTest] = useState<{ ok: boolean; steps: string[]; error: string } | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => { api.ldapGet().then(setCfg).catch((e) => setMsg({ kind: 'danger', text: e.message })) }, [])
  if (!cfg) return <div className="muted pad">Loading…</div>

  const set = (k: string, v: any) => setCfg({ ...cfg, [k]: v })
  const txt = (k: string, placeholder = '') => (
    <input value={cfg[k] ?? ''} placeholder={placeholder} onChange={(e) => set(k, e.target.value)} />
  )
  const chk = (k: string, label: string) => (
    <label className="check"><input type="checkbox" checked={!!cfg[k]} onChange={(e) => set(k, e.target.checked)} />{label}</label>
  )

  const domain = String(cfg.search_base || '').split(',').map((p) => p.trim())
    .filter((p) => p.toLowerCase().startsWith('dc=')).map((p) => p.slice(3)).join('.')
  const noSvc = anon || (!cfg.bind_password_set && !password)
  const fmt = String(cfg.user_bind_format || '').trim() || (domain ? `{username}@${domain}` : '')
  const signIn = fmt

  const save = async () => {
    setBusy(true); setMsg(null)
    try {
      const r = await api.ldapPut({ ...cfg, bind_password: anon ? '' : password, clear_bind_password: anon })
      setCfg(r); setPassword(''); setAnon(false)
      setMsg({ kind: 'ok', text: 'Settings saved.' })
    } catch (e: any) { setMsg({ kind: 'danger', text: e.message }) } finally { setBusy(false) }
  }
  const runTest = async () => {
    setBusy(true); setTest(null)
    try { setTest(await api.ldapTest({ ...cfg, bind_password: anon ? '' : password, clear_bind_password: anon, test_username: testUser, test_password: testPw })) }
    catch (e: any) { setTest({ ok: false, steps: [], error: e.message }) } finally { setBusy(false) }
  }

  return (
    <div className="admin-section">
      <div className="card">
        <div className="row space">
          <h3>Active Directory / LDAP</h3>
          {chk('enabled', 'Enable directory login')}
        </div>
        <p className="muted small">The built-in administrator (from the server .env file) always works, even if these settings are wrong.</p>
        <div className="grid2">
          <Field label="Server URL" hint="ldap://host:389 or ldaps://host:636">{txt('server_url', 'ldaps://dc01.corp.local:636')}</Field>
          <Field label="Timeout (seconds)"><input type="number" min={1} max={120} value={cfg.timeout} onChange={(e) => set('timeout', Number(e.target.value))} /></Field>
        </div>
        <div className="row gap wrap">
          {chk('start_tls', 'Use StartTLS (ldap://)')}
          {chk('verify_cert', 'Verify TLS certificate')}
        </div>
        <Field label="CA certificate path (in container)" hint="Optional, e.g. /data/certs/corp-ca.pem — place the file in the data volume">{txt('ca_cert_path', '/data/certs/ca.pem')}</Field>
        <Field label="User search base">{txt('search_base', 'DC=corp,DC=local')}</Field>
        <div className="grid2">
          <Field label="Service account (bind DN or UPN), optional" hint="Leave the password blank to let users sign in directly (no service account needed).">{txt('bind_dn', 'CN=svc-codingapp,OU=Service,DC=corp,DC=local')}</Field>
          <Field label="Service account password" hint={noSvc ? `No service account: users sign in as ${signIn || '(anonymous search)'} and are looked up with their own rights.` : 'A password is stored. Leave blank to keep it.'}>
            <input type="password" value={password} disabled={anon} onChange={(e) => setPassword(e.target.value)} placeholder={cfg.bind_password_set && !anon ? '••••••••' : ''} autoComplete="new-password" />
          </Field>
        </div>
        {cfg.bind_password_set && (
          <label className="check"><input type="checkbox" checked={anon} onChange={(e) => setAnon(e.target.checked)} />Remove the stored password (no service account)</label>
        )}
        {noSvc && (
          <Field label="User sign-in format" hint={`Used when there is no service account. {username} is what the user types. Leave blank for {username}@${domain || 'domain from search base'}; e.g. CORP\\{username}.`}>{txt('user_bind_format', domain ? `{username}@${domain}` : '{username}@corp.local')}</Field>
        )}
        <Field label="User filter" hint="{username} is replaced (escaped) with the login name. For UPN logins use (userPrincipalName={username})">{txt('user_filter')}</Field>
        <div className="grid2">
          <Field label="Display name attribute">{txt('display_name_attr', 'displayName')}</Field>
          <Field label="Email attribute">{txt('email_attr', 'mail')}</Field>
        </div>
        <Field label="Allowed group DN" hint="Optional. Only members of this group can sign in. Leave empty to allow all directory users.">{txt('required_group_dn', 'CN=CodingApp Users,OU=Groups,DC=corp,DC=local')}</Field>
        <Field label="Administrators group DN" hint="Optional. Members get access to this Administration page.">{txt('admin_group_dn', 'CN=CodingApp Admins,OU=Groups,DC=corp,DC=local')}</Field>
        {chk('nested_groups', 'Resolve nested group membership (Active Directory)')}
        {msg && <div className={`notice ${msg.kind}`}>{msg.text}</div>}
        <div className="row gap">
          <button className="btn primary" onClick={save} disabled={busy}>Save settings</button>
        </div>
      </div>

      <div className="card">
        <h3>Test connection</h3>
        <p className="muted small">Tests the values in the form above (saved or not). Optionally sign in as a user to check the filter and group membership{noSvc ? ' (without a service account the user\'s password is required)' : ''}. The test password is not stored.</p>
        <div className="row gap wrap">
          <input value={testUser} onChange={(e) => setTestUser(e.target.value)} placeholder="test username" />
          <input type="password" value={testPw} onChange={(e) => setTestPw(e.target.value)} placeholder={noSvc ? 'test user password' : 'test user password (optional)'} autoComplete="new-password" />
          <button className="btn" onClick={runTest} disabled={busy}>Test</button>
        </div>
        {test && (
          <div className={`notice ${test.ok ? 'ok' : 'danger'}`}>
            <div>
              {test.steps.map((s) => <div key={s}>✓ {s}</div>)}
              {test.error ? <div>✗ {test.error}</div> : <div><b>Success</b></div>}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function LlmTab() {
  const [info, setInfo] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const refresh = () => { setBusy(true); api.llmStatus().then(setInfo).catch((e) => setInfo({ ok: false, error: e.message })).finally(() => setBusy(false)) }
  useEffect(refresh, [])
  return (
    <>
    <div className="card">
      <div className="row space"><h3>LLM server</h3><button className="btn sm" onClick={refresh} disabled={busy}>Refresh</button></div>
      {!info ? <div className="muted">Loading…</div> : (
        <table className="kv">
          <tbody>
            <tr><th>Status</th><td>{info.ok ? <span className="badge ok">Connected</span> : <span className="badge danger">Unavailable</span>}</td></tr>
            <tr><th>Endpoint</th><td className="mono">{info.base_url}</td></tr>
            <tr><th>Model</th><td className="mono">{info.model || '–'}</td></tr>
            <tr><th>Context window</th><td>{fmtTokens(info.context_tokens)} tokens <span className="muted">({info.context_source})</span></td></tr>
            <tr><th>Max output per request</th><td>{fmtTokens(info.max_output_tokens)} tokens</td></tr>
            <tr><th>Token counting</th><td>{info.exact_tokenizer === true ? 'Exact (server /tokenize)' : info.exact_tokenizer === false ? 'Estimated (server has no /tokenize)' : 'Not used yet'}</td></tr>
            {info.models?.length > 1 && <tr><th>Models on server</th><td className="mono">{info.models.join(', ')}</td></tr>}
            {info.error && <tr><th>Error</th><td className="danger-text">{info.error}</td></tr>}
          </tbody>
        </table>
      )}
      <p className="muted small">These values come from the server environment (.env: LLM_BASE_URL, LLM_MODEL, LLM_CONTEXT_TOKENS, LLM_MAX_OUTPUT_TOKENS). Restart the container after changing them.</p>
    </div>
    {info && <ThinkingCard initial={info.thinking ?? 'default'} />}
    </>
  )
}

const THINKING_OPTIONS: { value: 'default' | 'on' | 'off'; label: string; hint: string }[] = [
  { value: 'on', label: 'On', hint: 'The model reasons step by step before answering. Better on hard bugs, but slower and uses more output tokens.' },
  { value: 'off', label: 'Off', hint: 'The model answers directly. Much faster; good for explanations and straightforward fixes.' },
  { value: 'default', label: 'Model default', hint: "Don't send the setting; the model's chat template decides (Qwen3: thinking on)." },
]

function ThinkingCard({ initial }: { initial: string }) {
  const [mode, setMode] = useState(initial)
  const [state, setState] = useState<{ kind: string; text: string } | null>(null)

  const choose = async (value: 'default' | 'on' | 'off') => {
    const prev = mode
    setMode(value)
    setState(null)
    try {
      await api.llmSettings(value)
      setState({ kind: 'ok', text: 'Saved. Applies to the next message in every chat.' })
    } catch (e: any) {
      setMode(prev)
      setState({ kind: 'danger', text: e.message })
    }
  }

  return (
    <div className="card">
      <h3>Thinking mode</h3>
      <p className="muted small">For reasoning models such as Qwen3, this sets <span className="mono">chat_template_kwargs.enable_thinking</span> on every request. When on, the reasoning appears in a collapsible “Reasoning” section above the answer.</p>
      <div className="options" role="radiogroup" aria-label="Thinking mode">
        {THINKING_OPTIONS.map((o) => (
          <label key={o.value} className={`option${mode === o.value ? ' selected' : ''}`}>
            <input type="radio" name="thinking" value={o.value} checked={mode === o.value} onChange={() => choose(o.value)} />
            <span>
              <span className="option-label">{o.label}</span>
              <span className="muted small">{o.hint}</span>
            </span>
          </label>
        ))}
      </div>
      {state && <div className={`notice ${state.kind}`}>{state.text}</div>}
    </div>
  )
}

function UsersTab() {
  const [users, setUsers] = useState<any[] | null>(null)
  useEffect(() => { api.users().then(setUsers).catch(() => setUsers([])) }, [])
  return (
    <div className="card">
      <h3>Users</h3>
      {!users ? <div className="muted">Loading…</div> : (
        <table className="table">
          <thead><tr><th>Username</th><th>Name</th><th>Source</th><th>Role</th><th>Chats</th><th>Last login</th></tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td className="mono">{u.username}</td><td>{u.display_name}</td>
                <td>{u.source === 'ldap' ? 'Directory' : 'Local'}</td><td>{u.is_admin ? 'Admin' : 'User'}</td>
                <td>{u.conversations}</td><td>{u.last_login ? new Date(u.last_login).toLocaleString() : '–'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

export function AdminPage() {
  const [tab, setTab] = useState<Tab>('ldap')
  return (
    <div className="admin">
      <header className="admin-head">
        <Link to="/" className="btn ghost sm"><Icon name="chevron" size={14} style={{ transform: 'rotate(180deg)' }} />Back to chat</Link>
        <h2>Administration</h2>
      </header>
      <div className="tabs">
        {(['ldap', 'llm', 'users'] as Tab[]).map((t) => (
          <button key={t} className={`tab${tab === t ? ' active' : ''}`} onClick={() => setTab(t)}>
            {t === 'ldap' ? 'Directory (LDAP)' : t === 'llm' ? 'LLM' : 'Users'}
          </button>
        ))}
      </div>
      <div className="admin-body">
        {tab === 'ldap' && <LdapTab />}
        {tab === 'llm' && <LlmTab />}
        {tab === 'users' && <UsersTab />}
      </div>
    </div>
  )
}
