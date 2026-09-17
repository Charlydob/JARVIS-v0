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

  constructor(private readonly options: QueueOptions<T>) {}

  enqueue(segment: SpeechSegment): void {
    let resolvePrepared!: (audio: T) => void
    let rejectPrepared!: (error: unknown) => void
    const prepared = new Promise<T>((resolve, reject) => {
      resolvePrepared = resolve
      rejectPrepared = reject
    })

    this.preparationTail = this.preparationTail
      .then(() => this.options.synthesize(segment.text))
      .then(resolvePrepared, rejectPrepared)
      .catch(() => undefined)

    this.playbackTail = this.playbackTail.then(async () => {
      try {
        const audio = await prepared
        await this.options.play(audio)
        if (segment.pauseAfterMs > 0) {
          const wait = this.options.wait ?? ((milliseconds: number) => new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds)))
          await wait(segment.pauseAfterMs)
        }
      } catch (error) {
        this.options.onError?.(error, segment)
      }
    })
  }

  async drain(): Promise<void> {
    await this.playbackTail
  }
}
