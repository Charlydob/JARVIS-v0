import { describe, expect, it } from 'vitest'
import { isStreamEventForTurn } from './client'

describe('stream turn isolation', () => {
  it('rejects a late result from the previous turn', () => {
    const lateResult = {
      type: 'result' as const,
      turn_id: 'turn-previous',
      message: 'Recordatorio creado, señor.',
      provider: 'core',
      conversation_id: 'conversation',
      message_id: 'message-previous',
      language: 'es',
    }
    const currentResult = { ...lateResult, turn_id: 'turn-current', message_id: 'message-current' }

    expect(isStreamEventForTurn(lateResult, 'turn-current')).toBe(false)
    expect(isStreamEventForTurn(currentResult, 'turn-current')).toBe(true)
  })
})
