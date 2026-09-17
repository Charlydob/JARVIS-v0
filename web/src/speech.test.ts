import { describe, expect, it } from 'vitest'
import { takeSpeechSegments } from './speech'

describe('speech segmentation', () => {
  it('keeps ordered complete sentences and the unfinished tail', () => {
    const result = takeSpeechSegments('Primera frase. Segunda frase completa. Tercera')
    expect(result.segments.map((item) => item.text)).toEqual(['Primera frase.', 'Segunda frase completa.'])
    expect(result.remainder).toBe('Tercera')
  })

  it('flushes the final text without losing or repeating words', () => {
    const result = takeSpeechSegments('A final sentence without punctuation', true)
    expect(result.segments.map((item) => item.text).join(' ')).toBe('A final sentence without punctuation')
    expect(result.remainder).toBe('')
  })

  it('preserves paragraph boundaries with only a short deliberate pause', () => {
    const result = takeSpeechSegments('Uno.\n\nDos. Tres', true)
    expect(result.segments.map((item) => [item.text, item.boundary, item.pauseAfterMs])).toEqual([
      ['Uno.', 'paragraph', 120],
      ['Dos.', 'sentence', 15],
      ['Tres', 'continuation', 0],
    ])
  })
})
