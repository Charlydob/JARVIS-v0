import { describe, expect, it } from 'vitest'
import { desiredVoiceCaptureMode, parseSpeechInterrupt } from './speechInterrupt'

describe('intentional speech interruption', () => {
  it('keeps normal capture off while thinking and enables only the reduced speaking listener', () => {
    expect(desiredVoiceCaptureMode(false, 'listening')).toBe('normal')
    expect(desiredVoiceCaptureMode(true, 'thinking')).toBeUndefined()
    expect(desiredVoiceCaptureMode(true, 'speaking')).toBe('interrupt')
  })

  it('ignores unrelated speech while JARVIS is speaking', () => {
    expect(parseSpeechInterrupt('Mira lo que está haciendo')).toEqual({ kind: 'ignore' })
    expect(parseSpeechInterrupt('Mira esto, fíjate en lo que está diciendo')).toEqual({ kind: 'ignore' })
    expect(parseSpeechInterrupt('vale')).toEqual({ kind: 'ignore' })
    expect(parseSpeechInterrupt('ok')).toEqual({ kind: 'ignore' })
  })

  it('stops for Jarvis alone and unambiguous standalone commands', () => {
    for (const transcript of ['Jarvis', 'Járvis.', 'Yarvis', 'Jarvis, calla', 'corta', 'para', 'stop', 'vale, vale', 'ok ok']) {
      expect(parseSpeechInterrupt(transcript)).toEqual({ kind: 'stop' })
    }
  })

  it('preserves the exact message following the Jarvis trigger', () => {
    expect(parseSpeechInterrupt('Jarvis, pero entonces busca otra fuente')).toEqual({
      kind: 'message', message: 'pero entonces busca otra fuente',
    })
    expect(parseSpeechInterrupt('Jarvis, pero entonces ¿cuánta corriente necesita?')).toEqual({
      kind: 'message', message: 'pero entonces ¿cuánta corriente necesita?',
    })
    expect(parseSpeechInterrupt('Jarvis, busca otra fuente')).toEqual({
      kind: 'message', message: 'busca otra fuente',
    })
  })
})
