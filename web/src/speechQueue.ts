import type { SpeechSegment } from './speech'

type QueueOptions<T> = {
  synthesize: (text: string) => Promise<T>
  play: (audio: T) => Promise<void>
  onError?: (error: unknown, segment: SpeechSegment) => void
  wait?: (milliseconds: number) => Promise<void>
}

export class PrefetchedSpeechQueue<T> {
  private preparationTail: Promise<void> = Promise.resolve()
  private playbackTail: Promise<void> = Promise.resolve()
  private generation = 0

  constructor(private readonly options: QueueOptions<T>) {}

  enqueue(segment: SpeechSegment): void {
    const generation = this.generation
    let resolvePrepared!: (audio: T) => void
    let rejectPrepared!: (error: unknown) => void
    const prepared = new Promise<T>((resolve, reject) => {
      resolvePrepared = resolve
      rejectPrepared = reject
    })

    this.preparationTail = this.preparationTail
      .then(async () => {
        if (generation !== this.generation) throw new SpeechQueueCancelled()
        const audio = await this.options.synthesize(segment.text)
        if (generation !== this.generation) throw new SpeechQueueCancelled()
        return audio
      })
      .then(resolvePrepared, rejectPrepared)
      .catch(() => undefined)

    this.playbackTail = this.playbackTail.then(async () => {
      try {
        const audio = await prepared
        if (generation !== this.generation) return
        await this.options.play(audio)
        if (generation !== this.generation) return
        if (segment.pauseAfterMs > 0) {
          const wait = this.options.wait ?? ((milliseconds: number) => new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds)))
          await wait(segment.pauseAfterMs)
        }
      } catch (error) {
        if (!(error instanceof SpeechQueueCancelled)) this.options.onError?.(error, segment)
      }
    })
  }

  cancel(): void {
    this.generation += 1
  }

  async drain(): Promise<void> {
    await this.playbackTail
  }
}

class SpeechQueueCancelled extends Error {}
