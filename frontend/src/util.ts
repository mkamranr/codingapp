export const basename = (p: string) => p.split('/').pop() || p

export function fmtTokens(n: number | undefined): string {
  if (n === undefined || n === null) return '–'
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M'
  if (n >= 10_000) return Math.round(n / 1000) + 'K'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return String(n)
}

const EXT: Record<string, string> = {
  python: 'py', py: 'py', javascript: 'js', js: 'js', jsx: 'jsx', typescript: 'ts', ts: 'ts', tsx: 'tsx',
  java: 'java', csharp: 'cs', cs: 'cs', c: 'c', cpp: 'cpp', 'c++': 'cpp', go: 'go', rust: 'rs', rs: 'rs',
  ruby: 'rb', php: 'php', html: 'html', css: 'css', scss: 'scss', json: 'json', yaml: 'yaml', yml: 'yml',
  bash: 'sh', sh: 'sh', shell: 'sh', powershell: 'ps1', sql: 'sql', kotlin: 'kt', swift: 'swift',
  xml: 'xml', markdown: 'md', md: 'md', dockerfile: 'Dockerfile', toml: 'toml', ini: 'ini',
}
export const extFor = (lang: string) => EXT[lang.toLowerCase()] ?? 'txt'

const LANG_BY_EXT: Record<string, string> = {
  py: 'python', js: 'javascript', mjs: 'javascript', cjs: 'javascript', jsx: 'jsx', ts: 'typescript', tsx: 'tsx',
  java: 'java', cs: 'csharp', c: 'c', h: 'c', cpp: 'cpp', cc: 'cpp', hpp: 'cpp', go: 'go', rs: 'rust',
  rb: 'ruby', php: 'php', html: 'markup', htm: 'markup', xml: 'markup', vue: 'markup', svelte: 'markup',
  css: 'css', scss: 'scss', less: 'less', json: 'json', yaml: 'yaml', yml: 'yaml', sh: 'bash', bash: 'bash',
  ps1: 'powershell', sql: 'sql', kt: 'kotlin', swift: 'swift', md: 'markdown', toml: 'toml', ini: 'ini',
  dockerfile: 'docker', gradle: 'groovy', scala: 'scala', r: 'r', dart: 'dart', lua: 'lua', pl: 'perl',
}
export function langForPath(path: string): string {
  const b = basename(path).toLowerCase()
  if (b === 'dockerfile') return 'docker'
  if (b === 'makefile') return 'makefile'
  return LANG_BY_EXT[b.split('.').pop() || ''] ?? 'text'
}

/** Parse "path=src/a.py action=delete" style fence meta (and lang:path shorthand). */
export function parseFence(className: string | undefined, meta: string | undefined) {
  let lang = (className || '').replace(/^language-/, '')
  let path: string | undefined
  const m = /(?:path|file|filename|filepath|name)\s*=\s*(?:"([^"]*)"|'([^']*)'|(\S+))/i.exec(meta || '')
  if (m) path = m[1] ?? m[2] ?? m[3]
  if (!path && lang.includes(':')) {
    const i = lang.indexOf(':')
    path = lang.slice(i + 1)
    lang = lang.slice(0, i)
  }
  const action = /action\s*=\s*["']?delete/i.test(meta || '') ? 'delete' : 'write'
  return { lang: lang || 'text', path, action }
}

/** Split Qwen-style <think> blocks from the visible answer. */
export function splitThink(content: string): { think: string; answer: string } {
  if (!content.includes('<think>') && !content.includes('</think>')) return { think: '', answer: content }
  const close = content.indexOf('</think>')
  if (close === -1) return { think: content.replace('<think>', ''), answer: '' }
  return {
    think: content.slice(0, close).replace('<think>', '').trim(),
    answer: content.slice(close + 8).replace(/^\s+/, ''),
  }
}

export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch { /* fall back */ }
  // Fallback for plain-http intranet deployments
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.select()
  let ok = false
  try { ok = document.execCommand('copy') } catch { ok = false }
  document.body.removeChild(ta)
  return ok
}

export function downloadText(filename: string, text: string) {
  const blob = new Blob([text], { type: 'application/octet-stream' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

export function downloadUrl(url: string) {
  const a = document.createElement('a')
  a.href = url
  a.download = ''
  document.body.appendChild(a)
  a.click()
  a.remove()
}
