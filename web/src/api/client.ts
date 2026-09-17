export interface StatusResponse {
  status: 'ready' | 'offline'
  gateway_version: string
  core_connected: boolean
  core: { providers?: Record<string, string>; ollama_ready?: boolean; last_seen?: string } | null
}

export interface ChatResponse {
  message: string
  provider: string
  conversation_id: string
  message_id: string
}

export interface HistoryItem {
  id: string
  conversation_id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  rating: 'good' | 'bad' | null
  correction: string | null
}

const apiUrl = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? ''

async function timedFetch(input: string, init: RequestInit = {}, timeoutMs = 90_000): Promise<Response> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(input, { ...init, signal: controller.signal })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw new Error('JARVIS ha tardado demasiado. Toca la cara para reintentar.')
    throw error
  } finally {
    window.clearTimeout(timer)
  }
}

async function checked(response: Response): Promise<Response> {
  if (response.ok) return response
  const body = await response.json().catch(() => ({ detail: `HTTP ${response.status}` })) as { detail?: string }
  throw new Error(body.detail || `HTTP ${response.status}`)
}

export async function getStatus(): Promise<StatusResponse> {
  return (await checked(await fetch(`${apiUrl}/api/status`, { cache: 'no-store' }))).json() as Promise<StatusResponse>
}

export interface UserLocation { latitude: number; longitude: number }

export async function sendMessage(message: string, conversationId?: string, location?: UserLocation): Promise<ChatResponse> {
  return (await checked(await timedFetch(`${apiUrl}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, conversation_id: conversationId, ...location })
  }))).json() as Promise<ChatResponse>
}

export async function transcribeAudio(audio: Blob): Promise<string> {
  const form = new FormData()
  form.append('file', audio, 'utterance.webm')
  const response = await checked(await timedFetch(`${apiUrl}/api/audio`, { method: 'POST', body: form }))
  const body = await response.json() as { transcript: string }
  return body.transcript.trim()
}

export async function synthesizeSpeech(text: string): Promise<Blob> {
  const response = await checked(await timedFetch(`${apiUrl}/api/tts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: text })
  }, 45_000))
  return response.blob()
}

export async function getHistory(): Promise<HistoryItem[]> {
  return (await checked(await fetch(`${apiUrl}/api/history?limit=200`, { cache: 'no-store' }))).json() as Promise<HistoryItem[]>
}

export async function sendFeedback(messageId: string, rating: 'good' | 'bad', correction?: string): Promise<void> {
  await checked(await fetch(`${apiUrl}/api/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message_id: messageId, rating, correction })
  }))
}
