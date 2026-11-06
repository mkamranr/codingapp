import { memo, useState } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { Icon } from '../icons'
import { useTheme } from '../theme'
import { basename, copyText, downloadText, extFor } from '../util'

const HIGHLIGHT_MAX_LINES = 4000

interface Props {
  code: string
  lang: string
  path?: string
  action?: string
  plain?: boolean // e.g. while streaming: skip expensive highlighting
}

function CodeBlockImpl({ code, lang, path, action, plain }: Props) {
  const { theme } = useTheme()
  const [copied, setCopied] = useState(false)
  const lines = code.split('\n').length
  const filename = path ? basename(path) : `snippet.${extFor(lang)}`

  const onCopy = async () => {
    if (await copyText(code)) {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }
  }

  const deleted = action === 'delete'
  return (
    <div className={`codeblock${path ? ' is-file' : ''}`}>
      <div className="codeblock-head">
        <span className="codeblock-title" title={path}>
          {path ? <><Icon name="file" size={14} /><span className="mono">{path}</span></> : <span className="mono muted">{lang}</span>}
          {deleted && <span className="badge danger">deleted</span>}
          {path && !deleted && <span className="muted small">{lines} lines</span>}
        </span>
        {!deleted && (
          <span className="codeblock-actions">
            <button className="btn ghost sm" onClick={onCopy} title="Copy code">
              <Icon name={copied ? 'check' : 'copy'} size={14} />{copied ? 'Copied' : 'Copy'}
            </button>
            <button className="btn ghost sm" onClick={() => downloadText(filename, code.endsWith('\n') ? code : code + '\n')}
              title={`Download ${filename}`}>
              <Icon name="download" size={14} />{path ? filename : 'Download'}
            </button>
          </span>
        )}
      </div>
      {!deleted && (plain || lines > HIGHLIGHT_MAX_LINES ? (
        <pre className="codeblock-plain"><code>{code}</code></pre>
      ) : (
        <SyntaxHighlighter language={lang} style={theme === 'dark' ? oneDark : oneLight}
          customStyle={{ margin: 0, borderRadius: 0, background: 'transparent', fontSize: 13 }}
          codeTagProps={{ style: { fontFamily: 'var(--mono)' } }}
          showLineNumbers={!!path && lines > 1} wrapLongLines={false}>
          {code}
        </SyntaxHighlighter>
      ))}
    </div>
  )
}

export const CodeBlock = memo(CodeBlockImpl)
