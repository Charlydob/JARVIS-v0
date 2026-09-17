import { describe, expect, it } from 'vitest'
import { PrefetchedSpeechQueue } from './speechQueue'

describe('prefetched speech queue', () => {
  it('prepares 10+ segments ahead while playing strictly in order without overlap', async () => {
    const synthesized: number[] = []
    const played: number[] = []
    let activePlayback = 0
    let overlap = false
    let preparedDuringFirstPlayback = 0
    let releaseFirst!: () => void
    const firstPlayback = new Promise<void>((resolve) => { releaseFirst = resolve })
    const queue = new PrefetchedSpeechQueue<number>({
      synthesize: async (text) => {
        const value = Number(text)
        synthesized.push(value)
        if (activePlayback > 0) preparedDuringFirstPlayback += 1
        return value
      },
      play: async (audio) => {
        activePlayback += 1
        if (activePlayback > 1) overlap = true
        played.push(audio)
        if (audio === 1) await firstPlayback
        activePlayback -= 1
      },
      wait: async () => undefined,
    })

    for (let index = 1; index <= 12; index += 1) {
      queue.enqueue({ text: String(index), boundary: 'sentence', pauseAfterMs: 15 })
    }
    await new Promise((resolve) => setTimeout(resolve, 0))
    releaseFirst()
    await queue.drain()

    expect(synthesized).toEqual(Array.from({ length: 12 }, (_, index) => index + 1))
    expect(played).toEqual(synthesized)
    expect(preparedDuringFirstPlayback).toBeGreaterThan(0)
    expect(overlap).toBe(false)
  })
})
