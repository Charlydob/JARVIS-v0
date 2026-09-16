export interface ChatResponse { message: string; provider: string; conversation_id: string }

const apiUrl = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? ''

export async function sendMessage(message: string, conversationId?: string): Promise<ChatResponse> {
  const response = await fetch(`${apiUrl}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, conversation_id: conversationId })
  })
  if (!response.ok) throw new Error(`API error: ${response.status}`)
  return response.json() as Promise<ChatResponse>
}
