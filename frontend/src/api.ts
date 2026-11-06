export interface User {
  id: number
  username: string
  display_name: string
  email: string
  is_admin: boolean
  source: 'local' | 'ldap'
}
export interface ConvSummary { id: number; title: string; root_name: string; updated_at: string | null }
export interface MsgFile { id: number; path: string; action: 'write' | 'delete' }
export interface CtxInfo {
  context_tokens?: number
  input_tokens?: number
  max_tokens?: number
  included?: string[]
  omitted?: string[]
  history_included?: number
  history_total?: number
  error?: string
}
export interface Msg {
  id: number
  role: 'user' | 'assistant'
  content: string
  reasoning: string
  finish_reason: string
  tokens: number
  context: CtxInfo
  files: MsgFile[]
  created_at?: string | null
  streaming?: boolean
}
export interface WsFile {
  id: number; path: string; tokens: number; version: number; modified: boolean; pinned: boolean; size: number
}
export interface Conversation extends ConvSummary { messages: Msg[]; files: WsFile[] }
export interface UploadResult {
  added: number; added_tokens: number; skipped: { path: string; reason: string }[]
  skipped_total: number; root_name: string; title: string; files: WsFile[]
}
export interface Health { ok: boolean; llm: boolean; model: string; context_tokens: number; max_upload_mb: number }

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

let unauthorizedHandler: (() => void) | null = null
export function onUnauthorized(fn: () => void) { unauthorizedHandler = fn }

async function errorFrom(r: Response): Promise<ApiError> {
  let msg = r.statusText || `HTTP ${r.status}`
  try {
    const j = await r.json()
    if (j?.detail) msg = typeof j.detail === 'string' ? j.detail : j.detail.map((d: any) => d.msg).join('; ')
  } catch { /* not json */ }
  if (r.status === 401) unauthorizedHandler?.()
  return new ApiError(r.status, msg)
}

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method,
    credentials: 'same-origin',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!r.ok) throw await errorFrom(r)
  return r.json() as Promise<T>
}

const enc = encodeURIComponent

export const api = {
  health: () => req<Health>('GET', '/api/health'),
  me: () => req<User>('GET', '/api/auth/me'),
  login: (username: string, password: string) => req<User>('POST', '/api/auth/login', { username, password }),
  logout: () => req('POST', '/api/auth/logout'),
  listConvs: () => req<ConvSummary[]>('GET', '/api/conversations'),
  createConv: () => req<ConvSummary>('POST', '/api/conversations', {}),
  getConv: (id: number) => req<Conversation>('GET', `/api/conversations/${id}`),
  renameConv: (id: number, title: string) => req<ConvSummary>('PATCH', `/api/conversations/${id}`, { title }),
  deleteConv: (id: number) => req('DELETE', `/api/conversations/${id}`),
  pin: (id: number, path: string, pinned: boolean) => req('POST', `/api/conversations/${id}/pins`, { path, pinned }),
  fileContent: (id: number, path: string) =>
    req<{ id: number; path: string; content: string; version: number; modified: boolean }>(
      'GET', `/api/conversations/${id}/file?path=${enc(path)}`),
  removeFile: (id: number, path?: string) =>
    req<{ files: WsFile[] }>('DELETE', `/api/conversations/${id}/files${path ? `?path=${enc(path)}` : ''}`),
  ldapGet: () => req<any>('GET', '/api/admin/ldap'),
  ldapPut: (cfg: any) => req<any>('PUT', '/api/admin/ldap', cfg),
  ldapTest: (cfg: any) => req<{ ok: boolean; steps: string[]; error: string }>('POST', '/api/admin/ldap/test', cfg),
  llmStatus: () => req<any>('GET', '/api/admin/llm'),
  llmSettings: (thinking: 'default' | 'on' | 'off') => req<{ thinking: string }>('PUT', '/api/admin/llm/settings', { thinking }),
  users: () => req<any[]>('GET', '/api/admin/users'),
}

export const exportUrl = (cid: number, mode: 'full' | 'changed', messageId?: number) =>
  `/api/conversations/${cid}/export.zip?mode=${mode}${messageId ? `&message_id=${messageId}` : ''}`
export const fileDownloadUrl = (fileId: number) => `/api/files/${fileId}/download`

export function uploadFiles(cid: number, files: File[], onProgress: (pct: number) => void): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const fd = new FormData()
    for (const f of files) {
      const rel = (f as any).webkitRelativePath as string | undefined
      fd.append('files', f, rel || f.name)
    }
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `/api/conversations/${cid}/files`)
    xhr.withCredentials = true
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100))
    xhr.onload = () => {
      let data: any = null
      try { data = JSON.parse(xhr.responseText) } catch { /* ignore */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data)
      else {
        if (xhr.status === 401) unauthorizedHandler?.()
        reject(new ApiError(xhr.status, data?.detail ?? `Upload failed (HTTP ${xhr.status})`))
      }
    }
    xhr.onerror = () => reject(new ApiError(0, 'Network error during upload'))
    xhr.send(fd)
  })
}

export type StreamHandler = (event: string, data: any) => void

export async function streamMessage(
  cid: number, body: { content: string; continue_last?: boolean }, onEvent: StreamHandler, signal: AbortSignal,
) {
  const r = await fetch(`/api/conversations/${cid}/messages`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  })
  if (!r.ok || !r.body) throw await errorFrom(r)
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let idx: number
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      let ev = 'message', data = ''
      for (const line of block.split('\n')) {
        if (line.startsWith('event: ')) ev = line.slice(7)
        else if (line.startsWith('data: ')) data += line.slice(6)
      }
      if (data) onEvent(ev, JSON.parse(data))
    }
  }
}
