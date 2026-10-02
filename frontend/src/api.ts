export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, options)
  if (!response.ok) {
    let message = `请求失败（${response.status}）`
    try { const error = await response.json(); message = typeof error.detail === 'string' ? error.detail : message } catch { /* retain HTTP status */ }
    throw new Error(message)
  }
  return response.json()
}
export function post<T>(path: string, body: unknown) { return api<T>(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)}) }
export function upload<T>(path: string, file: File) { const data = new FormData(); data.append('file', file); return api<T>(path, {method:'POST', body:data}) }
export function download(name: string, contents: string, type = 'text/csv;charset=utf-8') {
  const url = URL.createObjectURL(new Blob([contents], {type})); const a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
}
