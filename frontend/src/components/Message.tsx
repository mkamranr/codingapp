import { memo, useState } from 'react'
import { exportUrl, type Msg } from '../api'
import { Icon } from '../icons'
import { copyText, downloadUrl, fmtTokens } from '../util'
import { splitThink } from '../util'
import { Markdown } from './Markdown'

interface Props {
  msg: Msg
  cid: number
  isLast: boolean
  busy: boolean
  onContinue: () => void
  onOpenFile: (path: string) => void
}

function MessageImpl({ msg, cid, isLast, busy, onContinue, onOpenFile }: Props) {
  const [copied, setCopied] = useState(false)
  if (msg.role === 'user') {
    return (
      <div className="msg user">
        <div className="bubble">{msg.content}</div>
      </div>
    )
  }

  const { think, answer } = splitThink(msg.content)
  const reasoning = (msg.reasoning || '') + (think ? (msg.reasoning ? '\n' : '') + think : '')
  const changed = msg.files.filter((f) => f.action === 'write')
  const deleted = msg.files.filter((f) => f.action === 'delete')
  const fr = msg.finish_reason
  const persisted = msg.id > 0

  return (
    <div className="msg assistant">
      <div className="avatar"><Icon name="code" size={16} /></div>
      <div className="msg-body">
        {reasoning && (
          <details className="thinking" open={msg.streaming && !answer}>
            <summary>{msg.streaming && !answer ? 'Thinking…' : 'Reasoning'}</summary>
            <div className="thinking-text">{reasoning}</div>
          </details>
        )}
        {answer ? <Markdown text={answer} streaming={msg.streaming} />
          : msg.streaming && !reasoning && <div className="typing"><span /><span /><span /></div>}
        {msg.streaming && answer && <span className="cursor" />}

        {!msg.streaming && (msg.files.length > 0 || fr) && (
          <div className="msg-footer">
            {msg.files.length > 0 && (
              <div className="changed-files">
                <span className="muted small">{changed.length} file{changed.length === 1 ? '' : 's'} updated{deleted.length ? `, ${deleted.length} deleted` : ''}:</span>
                {msg.files.map((f) => (
                  <button key={f.id} className={`chip${f.action === 'delete' ? ' strike' : ''}`}
                    onClick={() => f.action === 'write' && onOpenFile(f.path)} title={f.path}>
                    <Icon name="file" size={12} />{f.path}
                  </button>
                ))}
              </div>
            )}
            <div className="msg-actions">
              <button className="btn ghost sm" onClick={async () => {
                if (await copyText(answer)) { setCopied(true); setTimeout(() => setCopied(false), 1500) }
              }}><Icon name={copied ? 'check' : 'copy'} size={14} />{copied ? 'Copied' : 'Copy answer'}</button>
              {persisted && msg.files.length > 0 && <>
                <button className="btn ghost sm" onClick={() => downloadUrl(exportUrl(cid, 'changed', msg.id))}
                  title="Zip with only the files changed in this answer (folder structure kept)">
                  <Icon name="download" size={14} />Changed files (.zip)
                </button>
                <button className="btn sm" onClick={() => downloadUrl(exportUrl(cid, 'full', msg.id))}
                  title="Whole project with these changes applied">
                  <Icon name="download" size={14} />Full project (.zip)
                </button>
              </>}
              {msg.context?.input_tokens ? (
                <span className="muted small" title="Prompt tokens / context window">
                  {fmtTokens(msg.context.input_tokens)} / {fmtTokens(msg.context.context_tokens)} ctx
                  {msg.context.omitted?.length ? ` · ${msg.context.omitted.length} files omitted` : ''}
                </span>
              ) : null}
            </div>
            {fr === 'length' && isLast && (
              <div className="notice warn">Output limit reached.
                <button className="btn sm" disabled={busy} onClick={onContinue}><Icon name="play" size={12} />Continue</button></div>
            )}
            {fr === 'stopped' && isLast && (
              <div className="notice">Stopped.
                <button className="btn sm" disabled={busy} onClick={onContinue}><Icon name="play" size={12} />Continue</button></div>
            )}
            {fr === 'error' && <div className="notice danger">{msg.context?.error || 'The request failed.'}</div>}
          </div>
        )}
      </div>
    </div>
  )
}

export const Message = memo(MessageImpl)
