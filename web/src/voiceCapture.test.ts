import { describe, expect, it } from 'vitest'
import { VoiceCaptureMachine } from './voiceCapture'

describe('voice capture state machine', () => {
  it('finalizes 20 utterances exactly once without retaining old chunks', () => {
    const machine = new VoiceCaptureMachine()
    const payloads: string[] = []

    for (let index = 0; index < 20; index += 1) {
      const id = `utterance-${index}`
      expect(machine.start(id)).toBe(true)
      expect(machine.phase).toBe('LISTENING')
      machine.addChunk(id, new Blob([`audio-${index}`]))
      expect(machine.requestFinalize(id)).toBe(true)
      expect(machine.requestFinalize(id)).toBe(false)
      const chunks = machine.takeFinalizedChunks(id)
      expect(chunks).toHaveLength(1)
      payloads.push(String(chunks[0].size))
      expect(machine.bufferedChunks()).toBe(0)
      machine.processing(id)
      machine.speaking(id)
      expect(machine.complete(id)).toBe(true)
      expect(machine.phase).toBe('IDLE')
    }

    expect(payloads).toHaveLength(20)
    expect(machine.bufferedChunks()).toBe(0)
  })

  it('manually finalizes one utterance once and rejects stale audio', () => {
    const machine = new VoiceCaptureMachine()
    expect(machine.start('manual-1')).toBe(true)
    machine.addChunk('manual-1', new Blob(['first']))
    expect(machine.requestFinalize('manual-1')).toBe(true)
    expect(machine.requestFinalize('manual-1')).toBe(false)
    expect(machine.takeFinalizedChunks('manual-1')).toHaveLength(1)
    expect(machine.addChunk('manual-1', new Blob(['late']))).toBe(false)
    machine.processing('manual-1')
    expect(machine.complete('manual-1')).toBe(true)
    expect(machine.start('manual-2')).toBe(true)
    expect(machine.bufferedChunks()).toBe(0)
  })
})
