import { useEffect, useState } from 'react'
import { api } from '../api'
import { Icon } from '../icons'
import { langForPath } from '../util'
import { CodeBlock } from './CodeBlock'

export function FileViewer({ cid, path, onClose }: { cid: number; path: string; onClose: () => void }) {
  const [data, setData] = useState<{ content: string; version: number; modified: boolean } | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.fileContent(cid, path).then(setData).catch((e) => setError(e.message))
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [cid, path, onClose])

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="small muted">{data ? (data.modified ? `Modified · version ${data.version}` : 'Original upload') : ''}</span>
          <button className="icon-btn" onClick={onClose} title="Close"><Icon name="x" size={16} /></button>
        </div>
        <div className="modal-body">
          {error && <div className="notice danger">{error}</div>}
          {data && <CodeBlock code={data.content.replace(/\n$/, '')} lang={langForPath(path)} path={path} />}
          {!data && !error && <div className="muted pad">Loading…</div>}
        </div>
      </div>
    </div>
  )
}
