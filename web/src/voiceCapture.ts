export type VoiceCapturePhase =
  | 'IDLE'
  | 'LISTENING'
  | 'FINALIZING'
  | 'TRANSCRIBING'
  | 'PROCESSING'
  | 'SPEAKING'

export class VoiceCaptureMachine {
  phase: VoiceCapturePhase = 'IDLE'
  utteranceId?: string
  private chunks: Blob[] = []

  start(utteranceId: string) {
    if (this.phase !== 'IDLE') return false
    this.utteranceId = utteranceId
    this.chunks = []
    this.phase = 'LISTENING'
    return true
  }

  addChunk(utteranceId: string, chunk: Blob) {
    if (utteranceId !== this.utteranceId || !['LISTENING', 'FINALIZING'].includes(this.phase)) return false
    if (chunk.size) this.chunks.push(chunk)
    return true
  }

  requestFinalize(utteranceId: string) {
    if (utteranceId !== this.utteranceId || this.phase !== 'LISTENING') return false
    this.phase = 'FINALIZING'
    return true
  }

  takeFinalizedChunks(utteranceId: string) {
    if (utteranceId !== this.utteranceId || this.phase !== 'FINALIZING') return []
    const finalized = this.chunks.splice(0)
    this.phase = 'TRANSCRIBING'
    return finalized
  }

  processing(utteranceId: string) {
    if (utteranceId === this.utteranceId && this.phase === 'TRANSCRIBING') this.phase = 'PROCESSING'
  }

  speaking(utteranceId: string) {
    if (utteranceId === this.utteranceId && ['TRANSCRIBING', 'PROCESSING'].includes(this.phase)) this.phase = 'SPEAKING'
  }

  complete(utteranceId: string) {
    if (utteranceId !== this.utteranceId) return false
    this.chunks = []
    this.utteranceId = undefined
    this.phase = 'IDLE'
    return true
  }

  abort() {
    this.chunks = []
    this.utteranceId = undefined
    this.phase = 'IDLE'
  }

  bufferedChunks() {
    return this.chunks.length
  }
}
