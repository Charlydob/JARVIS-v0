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
  language?: string
}

export interface HistoryItem {
  id: string
  conversation_id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  rating: 'good' | 'bad' | null
  reward: 1 | -1 | null
  reason: string | null
  correction: string | null
}

export interface ConversationStats {
  messages: number
  positives: number
  negatives: number
}

export interface AudioCaptureMetadata {
  durationMs: number
  speechMs: number
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
  const raw = await response.text().catch(() => '')
  let detail = raw.trim()
  try {
    const body = JSON.parse(raw) as { detail?: string }
    detail = body.detail?.trim() || detail
  } catch { /* retain the plain-text response */ }
  throw new Error(detail || `HTTP ${response.status}`)
}

export async function getStatus(): Promise<StatusResponse> {
  return (await checked(await fetch(`${apiUrl}/api/status`, { cache: 'no-store' }))).json() as Promise<StatusResponse>
}

export interface UserLocation { latitude: number; longitude: number }

export async function sendMessage(message: string, conversationId?: string, location?: UserLocation, language?: string, languageConfidence?: number): Promise<ChatResponse> {
  return (await checked(await timedFetch(`${apiUrl}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, conversation_id: conversationId, ...location, language, language_confidence: languageConfidence })
  }))).json() as Promise<ChatResponse>
}

export async function streamMessage(
  message: string,
  conversationId: string | undefined,
  location: UserLocation | undefined,
  language: string | undefined,
  languageConfidence: number | undefined,
  onChunk: (chunk: string) => void
): Promise<ChatResponse> {
  const response = await checked(await timedFetch(`${apiUrl}/api/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, conversation_id: conversationId, ...location, language, language_confidence: languageConfidence })
  }, 180_000))
  if (!response.body) throw new Error('El navegador no admite respuestas en streaming.')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result: ChatResponse | undefined

  const consume = (block: string) => {
    const data = block.split('\n').find((line) => line.startsWith('data: '))?.slice(6)
    if (!data) return
    const event = JSON.parse(data) as ({ type: 'chunk'; content: string } | ({ type: 'result' } & ChatResponse) | { type: 'error'; message: string })
    if (event.type === 'chunk') onChunk(event.content)
    else if (event.type === 'error') throw new Error(event.message)
    else result = event
  }

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() ?? ''
    for (const block of blocks) consume(block)
    if (done) break
  }
  if (buffer.trim()) consume(buffer)
  if (!result) throw new Error('La respuesta en streaming terminó antes de completarse.')
  return result
}

export async function transcribeAudio(audio: Blob, metadata?: AudioCaptureMetadata): Promise<{ transcript: string; language?: string; languageConfidence?: number }> {
  const form = new FormData()
  const extension = audio.type.includes('mp4') || audio.type.includes('m4a') || audio.type.includes('aac')
    ? 'm4a'
    : audio.type.includes('ogg') ? 'ogg' : 'webm'
  form.append('file', audio, `utterance.${extension}`)
  if (metadata) {
    form.append('duration_ms', String(Math.round(metadata.durationMs)))
    form.append('speech_ms', String(Math.round(metadata.speechMs)))
  }
  const response = await checked(await timedFetch(`${apiUrl}/api/audio`, { method: 'POST', body: form }))
  const body = await response.json() as { transcript: string; language?: string; language_confidence?: number }
  return { transcript: body.transcript.trim(), language: body.language, languageConfidence: body.language_confidence }
}

export async function synthesizeSpeech(text: string, language?: string): Promise<Blob> {
  const response = await checked(await timedFetch(`${apiUrl}/api/tts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: text, language })
  }, 45_000))
  return response.blob()
}

export async function getHistory(): Promise<HistoryItem[]> {
  return (await checked(await fetch(`${apiUrl}/api/history?limit=200`, { cache: 'no-store' }))).json() as Promise<HistoryItem[]>
}

export async function getStats(): Promise<ConversationStats> {
  return (await checked(await fetch(`${apiUrl}/api/stats`, { cache: 'no-store' }))).json() as Promise<ConversationStats>
}

export async function sendFeedback(messageId: string, rating: 'good' | 'bad', correction?: string, reason?: string): Promise<void> {
  await checked(await fetch(`${apiUrl}/api/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message_id: messageId, rating, correction, reason })
  }))
}
