import { useMemo, useState } from 'react'
import { exportUrl, type CtxInfo, type WsFile } from '../api'
import { Icon } from '../icons'
import { downloadUrl, fmtTokens } from '../util'

interface Props {
  cid: number | null
  rootName: string
  files: WsFile[]
  ctx: CtxInfo | null
  contextTokens: number
  onOpen: (path: string) => void
  onPin: (path: string, pinned: boolean) => void
  onRemove: (path?: string) => void
  open: boolean
}

interface Dir { name: string; path: string; dirs: Map<string, Dir>; files: WsFile[]; tokens: number }

function buildTree(files: WsFile[]): Dir {
  const root: Dir = { name: '', path: '', dirs: new Map(), files: [], tokens: 0 }
  for (const f of files) {
    const parts = f.path.split('/')
    let d = root
    d.tokens += f.tokens
    for (let i = 0; i < parts.length - 1; i++) {
      const p = parts.slice(0, i + 1).join('/')
      if (!d.dirs.has(parts[i])) d.dirs.set(parts[i], { name: parts[i], path: p, dirs: new Map(), files: [], tokens: 0 })
      d = d.dirs.get(parts[i])!
      d.tokens += f.tokens
    }
    d.files.push(f)
  }
  return root
}

export function FilePanel({ cid, rootName, files, ctx, contextTokens, onOpen, onPin, onRemove, open }: Props) {
  const tree = useMemo(() => buildTree(files), [files])
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [showOmitted, setShowOmitted] = useState(false)
  const total = tree.tokens
  const omitted = new Set(ctx?.omitted ?? [])
  const used = ctx?.input_tokens
  const ctxTokens = ctx?.context_tokens || contextTokens
  const pct = Math.min(100, Math.round(((used ?? total) / Math.max(ctxTokens, 1)) * 100))
  const modified = files.filter((f) => f.modified).length

  const toggle = (p: string) => setCollapsed((s) => { const n = new Set(s); n.has(p) ? n.delete(p) : n.add(p); return n })

  const renderDir = (d: Dir, depth: number): JSX.Element[] => {
    const out: JSX.Element[] = []
    for (const sub of [...d.dirs.values()].sort((a, b) => a.name.localeCompare(b.name))) {
      const isCollapsed = collapsed.has(sub.path)
      out.push(
        <div key={'d:' + sub.path} className="tree-row dir" style={{ paddingLeft: 8 + depth * 14 }} onClick={() => toggle(sub.path)}>
          <Icon name="chevron" size={12} className={isCollapsed ? '' : 'rot90'} />
          <Icon name="folder" size={13} /><span className="ellipsis">{sub.name}</span>
          <span className="tok">{fmtTokens(sub.tokens)}</span>
        </div>,
      )
      if (!isCollapsed) out.push(...renderDir(sub, depth + 1))
    }
    for (const f of [...d.files].sort((a, b) => a.path.localeCompare(b.path))) {
      const name = f.path.split('/').pop()
      out.push(
        <div key={'f:' + f.path} className={`tree-row file${omitted.has(f.path) ? ' omitted' : ''}`}
          style={{ paddingLeft: 22 + depth * 14 }} onClick={() => onOpen(f.path)}
          title={`${f.path}${omitted.has(f.path) ? ' — omitted from the last prompt (context full). Pin to include.' : ''}`}>
          <Icon name="file" size={13} /><span className="ellipsis">{name}</span>
          {f.modified && <span className="dot" title="Modified by the assistant" />}
          <span className="tok">{fmtTokens(f.tokens)}</span>
          <button className={`icon-btn pin${f.pinned ? ' on' : ''}`} title={f.pinned ? 'Unpin' : 'Pin: always include in context'}
            onClick={(e) => { e.stopPropagation(); onPin(f.path, !f.pinned) }}><Icon name="pin" size={12} /></button>
          <button className="icon-btn rm" title="Remove from project" onClick={(e) => { e.stopPropagation(); onRemove(f.path) }}>
            <Icon name="x" size={12} /></button>
        </div>,
      )
    }
    return out
  }

  return (
    <aside className={`filepanel${open ? ' open' : ''}`}>
      <div className="panel-head">
        <div>
          <div className="panel-title">{rootName || 'Project files'}</div>
          <div className="muted small">{files.length} files · {fmtTokens(total)} tokens{modified ? ` · ${modified} modified` : ''}</div>
        </div>
      </div>

      <div className="meter" title="Tokens used by the last prompt vs. the model's context window">
        <div className="meter-bar"><div className={pct > 90 ? 'hot' : ''} style={{ width: `${pct}%` }} /></div>
        <div className="small row space">
          <span>{used ? `Last prompt ${fmtTokens(used)}` : `Project ${fmtTokens(total)}`}</span>
          <span className="muted">of {fmtTokens(ctxTokens)} context</span>
        </div>
        {omitted.size > 0 && (
          <button className="link small warn-text" onClick={() => setShowOmitted((v) => !v)}>
            {omitted.size} file{omitted.size > 1 ? 's' : ''} didn't fit in the last prompt {showOmitted ? '▴' : '▾'}
          </button>
        )}
        {showOmitted && <div className="omitted-list small mono">{[...omitted].map((p) => <div key={p}>{p}</div>)}</div>}
      </div>

      <div className="tree">
        {files.length === 0
          ? <div className="muted small pad">Upload source files, a folder, or a .zip of your project. Drag & drop works too.</div>
          : renderDir(tree, 0)}
      </div>

      {cid && files.length > 0 && (
        <div className="panel-foot">
          <button className="btn primary block" onClick={() => downloadUrl(exportUrl(cid, 'full'))}>
            <Icon name="download" size={14} />Download project (.zip)</button>
          {modified > 0 && <button className="btn block" onClick={() => downloadUrl(exportUrl(cid, 'changed'))}>
            <Icon name="download" size={14} />All changed files (.zip)</button>}
          <button className="btn ghost block sm" onClick={() => confirm('Remove all files from this conversation?') && onRemove()}>
            <Icon name="trash" size={13} />Clear files</button>
        </div>
      )}
    </aside>
  )
}
