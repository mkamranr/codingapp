import { memo, isValidElement, type ReactNode } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { parseFence } from '../util'
import { CodeBlock } from './CodeBlock'

function textOf(node: ReactNode): string {
  if (typeof node === 'string') return node
  if (Array.isArray(node)) return node.map(textOf).join('')
  if (isValidElement(node)) return textOf((node.props as any).children)
  return ''
}

function MarkdownImpl({ text, streaming }: { text: string; streaming?: boolean }) {
  const components: Components = {
    pre({ node, children }) {
      const codeEl: any = node?.children?.[0]
      const cls: string | undefined = Array.isArray(codeEl?.properties?.className)
        ? codeEl.properties.className.join(' ')
        : codeEl?.properties?.className
      const meta: string | undefined = codeEl?.data?.meta
      const { lang, path, action } = parseFence(cls, meta)
      const code = textOf(children).replace(/\n$/, '')
      return <CodeBlock code={code} lang={lang} path={path} action={action} plain={streaming} />
    },
    a({ href, children }) {
      return <a href={href} target="_blank" rel="noreferrer noopener">{children}</a>
    },
  }
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>{text}</ReactMarkdown>
    </div>
  )
}

export const Markdown = memo(MarkdownImpl)
