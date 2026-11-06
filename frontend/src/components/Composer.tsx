import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { Icon } from '../icons'

interface Props {
  busy: boolean
  uploading: number | null
  onSend: (text: string) => void
  onStop: () => void
  onFiles: (files: File[]) => void
  maxUploadMb: number
}

export function Composer({ busy, uploading, onSend, onStop, onFiles, maxUploadMb }: Props) {
  const [text, setText] = useState('')
  const ta = useRef<HTMLTextAreaElement>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const dirInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const el = ta.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 320) + 'px'
  }, [text])

  useEffect(() => { dirInput.current?.setAttribute('webkitdirectory', '') }, [])

  const submit = () => {
    const t = text.trim()
    if (!t || busy) return
    onSend(t)
    setText('')
  }
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit()
    }
  }
  const pick = (list: FileList | null) => {
    if (list && list.length) onFiles(Array.from(list))
  }

  return (
    <div className="composer">
      {uploading !== null && (
        <div className="upload-progress"><div style={{ width: `${uploading}%` }} /><span>Uploading… {uploading}%</span></div>
      )}
      <div className="composer-box">
        <textarea ref={ta} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey} rows={1}
          placeholder="Ask about the code, or ask to fix / refactor / add a feature…  (Shift+Enter for new line)" />
        <div className="composer-bar">
          <div className="row gap-xs">
            <button className="btn ghost sm" onClick={() => fileInput.current?.click()} disabled={uploading !== null}
              title={`Upload source files or a .zip (max ${maxUploadMb} MB)`}>
              <Icon name="clip" size={15} />Files / .zip
            </button>
            <button className="btn ghost sm" onClick={() => dirInput.current?.click()} disabled={uploading !== null}
              title="Upload a whole folder">
              <Icon name="folder" size={15} />Folder
            </button>
            <input ref={fileInput} type="file" multiple hidden onChange={(e) => { pick(e.target.files); e.target.value = '' }} />
            <input ref={dirInput} type="file" multiple hidden onChange={(e) => { pick(e.target.files); e.target.value = '' }} />
          </div>
          {busy ? (
            <button className="btn danger" onClick={onStop}><Icon name="stop" size={14} />Stop</button>
          ) : (
            <button className="btn primary" onClick={submit} disabled={!text.trim()}><Icon name="send" size={14} />Send</button>
          )}
        </div>
      </div>
    </div>
  )
}
