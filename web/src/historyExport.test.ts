import { describe, expect, it, vi } from 'vitest'
import type { HistoryItem } from './api/client'
import { formatHistorySelection } from './historyExport'

describe('formatHistorySelection', () => {
  it('copies selected messages chronologically with clean roles and exact text', () => {
    vi.spyOn(Date.prototype, 'toLocaleTimeString').mockImplementation(function (this: Date) {
      return this.toISOString().slice(11, 16)
    })
    const items = Array.from({ length: 6 }, (_, index): HistoryItem => ({
      id: String(index + 1), conversation_id: 'c', role: index % 2 === 0 ? 'user' : 'assistant',
      content: index === 3 ? 'assistant: Respuesta exacta' : `Mensaje ${index + 1}`,
      created_at: `2026-09-18T08:${String(55 + index).padStart(2, '0')}:00.000Z`,
      rating: null, reward: null, reason: null, correction: null,
      reason_code: null, comment: null, expected_behavior: null,
    }))

    const copied = formatHistorySelection([items[4], items[1], items[3], items[2]])

    expect(copied).toBe(
      '[08:56] JARVIS:\nMensaje 2\n\n' +
      '[08:57] Usuario:\nMensaje 3\n\n' +
      '[08:58] JARVIS:\nRespuesta exacta\n\n' +
      '[08:59] Usuario:\nMensaje 5'
    )
    vi.restoreAllMocks()
  })
})
