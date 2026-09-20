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

  it('never starts another utterance while finalizing, transcribing, processing, or speaking', () => {
    const machine = new VoiceCaptureMachine()
    expect(machine.start('active')).toBe(true)
    expect(machine.start('overlap-listening')).toBe(false)
    machine.addChunk('active', new Blob(['audio']))
    expect(machine.requestFinalize('active')).toBe(true)
    expect(machine.start('overlap-finalizing')).toBe(false)
    machine.takeFinalizedChunks('active')
    expect(machine.start('overlap-transcribing')).toBe(false)
    machine.processing('active')
    expect(machine.start('overlap-processing')).toBe(false)
    machine.speaking('active')
    expect(machine.start('overlap-speaking')).toBe(false)
    expect(machine.complete('active')).toBe(true)
    expect(machine.start('next-turn')).toBe(true)
  })

  it('keeps every MediaRecorder chunk contiguous until finalization', async () => {
    const machine = new VoiceCaptureMachine()
    expect(machine.start('container-safe')).toBe(true)
    machine.addChunk('container-safe', new Blob(['webm-header']))
    for (let index = 0; index < 20; index += 1) {
      machine.addChunk('container-safe', new Blob([`chunk-${index}`]))
    }
    expect(machine.bufferedChunks()).toBe(21)
    machine.requestFinalize('container-safe')
    const chunks = machine.takeFinalizedChunks('container-safe')
    expect(await chunks[0].text()).toBe('webm-header')
    expect(await chunks[1].text()).toBe('chunk-0')
    expect(await chunks[10].text()).toBe('chunk-9')
    expect(await chunks.at(-1)?.text()).toBe('chunk-19')
  })

  it('progresses one valid finalizing utterance to processing exactly once', () => {
    const machine = new VoiceCaptureMachine()
    expect(machine.start('watchdog')).toBe(true)
    machine.addChunk('watchdog', new Blob(['valid-audio']))
    expect(machine.requestFinalize('watchdog')).toBe(true)
    expect(machine.takeFinalizedChunks('watchdog')).toHaveLength(1)
    expect(machine.takeFinalizedChunks('watchdog')).toHaveLength(0)
    expect(machine.processing('watchdog')).toBe(true)
    expect(machine.processing('watchdog')).toBe(false)
    expect(machine.phase).toBe('PROCESSING')
  })
})
