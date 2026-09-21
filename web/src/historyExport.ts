import type { HistoryItem } from './api/client'

export function formatHistorySelection(items: HistoryItem[]): string {
  return [...items]
    .sort((left, right) => new Date(left.created_at).getTime() - new Date(right.created_at).getTime())
    .map((item) => {
      const time = new Date(item.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      const role = item.role === 'user' ? 'Usuario' : 'JARVIS'
      const content = item.role === 'assistant'
        ? item.content.replace(/^\s*assistant\s*:?\s*/i, '').trim()
        : item.content.trim()
      return `[${time}] ${role}:\n${content}`
    })
    .join('\n\n')
}

export async function copyPlainText(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value)
    return
  }
  const area = document.createElement('textarea')
  area.value = value
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.focus()
  area.select()
  const copied = document.execCommand('copy')
  area.remove()
  if (!copied) throw new Error('El navegador no permitió copiar la conversación.')
}

export async function copyHistorySelection(
  items: HistoryItem[], copy: (value: string) => Promise<void> = copyPlainText,
): Promise<{ copied: boolean; notice: 'Copiado' | 'No se pudo copiar' }> {
  try {
    await copy(formatHistorySelection(items))
    return { copied: true, notice: 'Copiado' }
  } catch {
    return { copied: false, notice: 'No se pudo copiar' }
  }
}
