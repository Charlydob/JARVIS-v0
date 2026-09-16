import { describe, expect, it } from 'vitest'
import { transition } from './machine'

describe('Jarvis state machine', () => {
  it('completes a conversation cycle', () => {
    let state = transition('sleeping', { type: 'WAKE' })
    state = transition(state, { type: 'START_LISTENING' })
    state = transition(state, { type: 'SUBMIT' })
    state = transition(state, { type: 'RESPONSE' })
    state = transition(state, { type: 'SPEECH_END' })
    expect(state).toBe('idle')
  })

  it('ignores invalid transitions', () => {
    expect(transition('sleeping', { type: 'RESPONSE' })).toBe('sleeping')
  })
})
