import { describe, expect, it } from 'vitest'
import { transition } from './machine'

describe('Jarvis state machine', () => {
  it('completes a continuous voice cycle', () => {
    let state = transition('sleeping', { type: 'CORE_ONLINE' })
    state = transition(state, { type: 'START_LISTENING' })
    state = transition(state, { type: 'SUBMIT' })
    state = transition(state, { type: 'RESPONSE' })
    state = transition(state, { type: 'SPEECH_END' })
    expect(state).toBe('listening')
  })

  it('mutes and resumes without pretending the core is online', () => {
    expect(transition('listening', { type: 'MUTE' })).toBe('muted')
    expect(transition('muted', { type: 'UNMUTE' })).toBe('idle')
    expect(transition('muted', { type: 'CORE_OFFLINE' })).toBe('sleeping')
  })

  it('accepts an intentional replacement turn while speaking', () => {
    expect(transition('speaking', { type: 'SUBMIT' })).toBe('thinking')
  })
})
