import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  api, streamMessage, uploadFiles,
  type Conversation, type ConvSummary, type CtxInfo, type Health, type Msg, type UploadResult, type User,
} from '../api'
import { Composer } from '../components/Composer'
import { FilePanel } from '../components/FilePanel'
import { FileViewer } from '../components/FileViewer'
import { Message } from '../components/Message'
import { Sidebar } from '../components/Sidebar'
import { Icon } from '../icons'
import { fmtTokens } from '../util'

const SUGGESTIONS = [
  'Review the whole project and list bugs, ordered by severity.',
  'Explain the architecture and how the main components interact.',
  'Find and fix all bugs. Return the complete fixed files.',
  'Add input validation, error handling and logging where missing.',
]

const blankMsg = (role: 'user' | 'assistant', content = ''): Msg => ({
  id: -Math.floor(Math.random() * 1e9), role, content, reasoning: '', finish_reason: '', tokens: 0,
  context: {}, files: [],
})

function lastCtx(c: Conversation): CtxInfo | null {
  for (let i = c.messages.length - 1; i >= 0; i--) {
    const m = c.messages[i]
    if (m.role === 'assistant' && m.context?.input_tokens) return m.context
  }
  return null
}

export function ChatPage({ user, onLogout }: { user: User; onLogout: () => void }) {
  const { id } = useParams()
  const activeId = id ? Number(id) : null
  const navigate = useNavigate()
  const [convs, setConvs] = useState<ConvSummary[]>([])
  const [conv, setConv] = useState<Conversation | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [ctx, setCtx] = useState<CtxInfo | null>(null)
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [upload, setUpload] = useState<UploadResult | null>(null)
  const [viewer, setViewer] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [panelOpen, setPanelOpen] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const skipLoad = useRef<number | null>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const stick = useRef(true)

  const refreshConvs = useCallback(() => { api.listConvs().then(setConvs).catch(() => {}) }, [])
  const load = useCallback((cid: number) =>
    api.getConv(cid).then((c) => { setConv(c); setCtx(lastCtx(c)) }), [])

  useEffect(() => {
    refreshConvs()
    api.health().then(setHealth).catch(() => {})
  }, [refreshConvs])

  useEffect(() => {
    setUpload(null)
    setError('')
    if (activeId === null) { setConv(null); setCtx(null); return }
    if (skipLoad.current === activeId) { skipLoad.current = null; return }
    load(activeId).catch((e) => { setError(e.message); navigate('/') })
    stick.current = true
  }, [activeId, load, navigate])

  // auto-scroll while the user is at the bottom
  useEffect(() => {
    const el = scroller.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [conv?.messages])

  const onScroll = () => {
    const el = scroller.current
    if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

  async function ensureConv(): Promise<number> {
    if (conv) return conv.id
    const c = await api.createConv()
    const full: Conversation = { ...c, messages: [], files: [] }
    setConv(full)
    skipLoad.current = c.id
    navigate(`/c/${c.id}`)
    setConvs((cs) => [c, ...cs])
    return c.id
  }

  const updateLast = (cid: number, fn: (m: Msg) => Msg) =>
    setConv((c) => {
      if (!c || c.id !== cid || !c.messages.length) return c
      const msgs = c.messages.slice()
      msgs[msgs.length - 1] = fn(msgs[msgs.length - 1])
      return { ...c, messages: msgs }
    })

  async function send(text: string, continueLast = false) {
    if (busy) return
    setError('')
    let cid: number
    try { cid = await ensureConv() } catch (e: any) { setError(e.message); return }
    const ac = new AbortController()
    abortRef.current = ac
    setBusy(true)
    stick.current = true
    setConv((c) => {
      if (!c) return c
      const msgs = c.messages.slice()
      if (continueLast) {
        const last = msgs[msgs.length - 1]
        msgs[msgs.length - 1] = { ...last, streaming: true, finish_reason: '' }
      } else {
        msgs.push(blankMsg('user', text), { ...blankMsg('assistant'), streaming: true })
      }
      return { ...c, messages: msgs }
    })

    let pending = '', pendingR = '', raf = 0
    const flush = () => {
      raf = 0
      if (!pending && !pendingR) return
      const t = pending, r = pendingR
      pending = ''; pendingR = ''
      updateLast(cid, (m) => ({ ...m, content: m.content + t, reasoning: m.reasoning + r }))
    }
    const schedule = () => { if (!raf) raf = requestAnimationFrame(flush) }

    try {
      await streamMessage(cid, { content: text, continue_last: continueLast }, (ev, d) => {
        switch (ev) {
          case 'start':
            updateLast(cid, (m) => ({ ...m, id: d.message_id }))
            break
          case 'context':
            setCtx(d)
            updateLast(cid, (m) => ({ ...m, context: d }))
            break
          case 'delta': pending += d.t; schedule(); break
          case 'reasoning': pendingR += d.t; schedule(); break
          case 'files':
            flush()
            updateLast(cid, (m) => ({ ...m, files: d.files }))
            break
          case 'done':
            updateLast(cid, (m) => ({ ...m, finish_reason: d.finish_reason }))
            break
          case 'error':
            setError(d.message)
            updateLast(cid, (m) => ({ ...m, finish_reason: 'error', context: { ...m.context, error: d.message } }))
            break
        }
      }, ac.signal)
    } catch (e: any) {
      if (e?.name !== 'AbortError') setError(e.message || String(e))
    } finally {
      if (raf) cancelAnimationFrame(raf)
      flush()
      updateLast(cid, (m) => ({ ...m, streaming: false }))
      setBusy(false)
      abortRef.current = null
      // re-sync with the server (ids, files, finish reasons)
      setTimeout(() => { load(cid).catch(() => {}); refreshConvs() }, ac.signal.aborted ? 700 : 50)
    }
  }

  async function handleFiles(files: File[]) {
    const max = (health?.max_upload_mb ?? 25) * 1024 * 1024
    const total = files.reduce((s, f) => s + f.size, 0)
    if (total > max) {
      setError(`Upload is ${(total / 1048576).toFixed(1)} MB; the limit is ${health?.max_upload_mb ?? 25} MB.`)
      return
    }
    setError('')
    let cid: number
    try { cid = await ensureConv() } catch (e: any) { setError(e.message); return }
    setUploading(0)
    try {
      const r = await uploadFiles(cid, files, setUploading)
      setConv((c) => (c && c.id === cid ? { ...c, files: r.files, root_name: r.root_name, title: r.title } : c))
      setUpload(r)
      refreshConvs()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setUploading(null)
    }
  }

  const onPin = async (path: string, pinned: boolean) => {
    if (!conv) return
    setConv({ ...conv, files: conv.files.map((f) => (f.path === path ? { ...f, pinned } : f)) })
    await api.pin(conv.id, path, pinned).catch((e) => setError(e.message))
  }
  const onRemove = async (path?: string) => {
    if (!conv) return
    try {
      const r = await api.removeFile(conv.id, path)
      setConv({ ...conv, files: r.files, root_name: path ? conv.root_name : '' })
    } catch (e: any) { setError(e.message) }
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    if (e.dataTransfer.files?.length) handleFiles(Array.from(e.dataTransfer.files))
  }

  const closeViewer = useCallback(() => setViewer(null), [])
  const messages = conv?.messages ?? []

  return (
    <div className="layout">
      <Sidebar user={user} convs={convs} activeId={activeId} open={sidebarOpen}
        onNew={() => { setSidebarOpen(false); navigate('/') }}
        onSelect={(cid) => { setSidebarOpen(false); navigate(`/c/${cid}`) }}
        onRename={async (cid, title) => {
          await api.renameConv(cid, title).catch(() => {})
          refreshConvs()
          if (conv?.id === cid) setConv({ ...conv, title })
        }}
        onDelete={async (cid) => {
          await api.deleteConv(cid).catch(() => {})
          refreshConvs()
          if (cid === activeId) navigate('/')
        }}
        onLogout={onLogout} />

      <main className="main" onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={(e) => { if (e.currentTarget === e.target) setDragging(false) }} onDrop={onDrop}>
        <header className="topbar">
          <button className="icon-btn mobile-only" onClick={() => setSidebarOpen((v) => !v)}><Icon name="menu" size={18} /></button>
          <div className="topbar-title ellipsis">{conv?.title || 'New chat'}</div>
          <div className="row gap-xs">
            {health && (
              <span className={`badge${health.llm ? '' : ' danger'}`} title="Model and context window">
                {health.llm ? `${health.model} · ${fmtTokens(health.context_tokens)} ctx` : 'LLM offline'}
              </span>
            )}
            <button className="icon-btn panel-toggle" onClick={() => setPanelOpen((v) => !v)} title="Project files">
              <Icon name="panel" size={18} /></button>
          </div>
        </header>

        <div className="messages" ref={scroller} onScroll={onScroll}>
          {messages.length === 0 ? (
            <div className="empty">
              <div className="empty-icon"><Icon name="code" size={28} /></div>
              <h1>What are we coding today?</h1>
              <p className="muted">
                Upload source files, a folder or a <b>.zip</b> of your project (up to {health?.max_upload_mb ?? 25} MB),
                then ask a question or ask for a fix. The whole project is sent to the model,
                up to its {fmtTokens(health?.context_tokens)}-token context window.
              </p>
              <div className="suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="suggestion" disabled={busy} onClick={() => send(s)}>{s}</button>
                ))}
              </div>
            </div>
          ) : (
            <div className="thread">
              {messages.map((m, i) => (
                <Message key={m.id} msg={m} cid={conv!.id} isLast={i === messages.length - 1} busy={busy}
                  onContinue={() => send('', true)} onOpenFile={setViewer} />
              ))}
            </div>
          )}
        </div>

        <div className="bottom">
          {error && <div className="notice danger closable">{error}<button className="icon-btn" onClick={() => setError('')}><Icon name="x" size={14} /></button></div>}
          {upload && (
            <div className="notice ok closable">
              <span>
                Added <b>{upload.added}</b> files ({fmtTokens(upload.added_tokens)} tokens){upload.root_name ? <> from <b>{upload.root_name}</b></> : null}.
                {upload.skipped_total > 0 && (
                  <details className="skipped"><summary>{upload.skipped_total} skipped</summary>
                    <div className="mono small">{upload.skipped.map((s) => <div key={s.path}>{s.path} — {s.reason}</div>)}</div>
                  </details>
                )}
              </span>
              <button className="icon-btn" onClick={() => setUpload(null)}><Icon name="x" size={14} /></button>
            </div>
          )}
          <Composer busy={busy} uploading={uploading} onSend={(t) => send(t)} onStop={() => abortRef.current?.abort()}
            onFiles={handleFiles} maxUploadMb={health?.max_upload_mb ?? 25} />
        </div>

        {dragging && <div className="dropzone"><Icon name="clip" size={28} /><div>Drop files or a .zip to add them to the project</div></div>}
      </main>

      <FilePanel cid={conv?.id ?? null} rootName={conv?.root_name ?? ''} files={conv?.files ?? []} ctx={ctx}
        contextTokens={health?.context_tokens ?? 0} onOpen={setViewer} onPin={onPin} onRemove={onRemove} open={panelOpen} />

      {viewer && conv && <FileViewer cid={conv.id} path={viewer} onClose={closeViewer} />}
      {(sidebarOpen || panelOpen) && <div className="scrim" onClick={() => { setSidebarOpen(false); setPanelOpen(false) }} />}
    </div>
  )
}
