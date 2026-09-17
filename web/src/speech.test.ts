import { describe, expect, it } from 'vitest'
import { takeSpeechSegments } from './speech'

describe('speech segmentation', () => {
  it('keeps ordered complete sentences and the unfinished tail', () => {
    const result = takeSpeechSegments('Primera frase. Segunda frase completa. Tercera')
    expect(result.segments).toEqual(['Primera frase.', 'Segunda frase completa.'])
    expect(result.remainder).toBe('Tercera')
  })

  it('flushes the final text without losing or repeating words', () => {
    const result = takeSpeechSegments('A final sentence without punctuation', true)
    expect(result.segments.join(' ')).toBe('A final sentence without punctuation')
    expect(result.remainder).toBe('')
  })
})
