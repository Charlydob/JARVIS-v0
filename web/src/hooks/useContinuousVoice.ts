import { useEffect, useRef } from 'react'

interface ContinuousVoiceOptions {
  enabled: boolean
  retainMicrophone: boolean
  onListening: () => void
  onUtterance: (audio: Blob) => void
  onError: (message: string) => void
}

const SILENCE_MS = 3000
const MIN_VOICE_THRESHOLD = 0.012
const NOISE_MULTIPLIER = 2.8
const REQUIRED_VOICE_FRAMES = 3

export function useContinuousVoice({ enabled, retainMicrophone, onListening, onUtterance, onError }: ContinuousVoiceOptions) {
  const callbacks = useRef({ onListening, onUtterance, onError })
  const streamRef = useRef<MediaStream>()
  const retainRef = useRef(retainMicrophone)
  callbacks.current = { onListening, onUtterance, onError }
  retainRef.current = retainMicrophone

  useEffect(() => {
    if (retainMicrophone) return
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = undefined
  }, [retainMicrophone])

  useEffect(() => {
    if (!enabled) return

    let cancelled = false
    let animationFrame = 0
    let stream: MediaStream | undefined
    let context: AudioContext | undefined
    let recorder: MediaRecorder | undefined

    const start = async () => {
      try {
        const retained = streamRef.current
        stream = retained?.getAudioTracks().some((track) => track.readyState === 'live')
          ? retained
          : await navigator.mediaDevices.getUserMedia({
              audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
            })
        streamRef.current = stream
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop())
          return
        }

        context = new AudioContext()
        const source = context.createMediaStreamSource(stream)
        const analyser = context.createAnalyser()
        analyser.fftSize = 1024
        source.connect(analyser)

        const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : ''
        recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
        const samples = new Uint8Array(analyser.fftSize)
        let heardVoice = false
        let lastVoiceAt = 0
        let noiseFloor = 0.006
        let voiceFrames = 0
        let containerHeader: Blob | undefined
        let preRoll: Blob[] = []
        const utterance: Blob[] = []

        recorder.ondataavailable = (event) => {
          if (!event.data.size) return
          if (!containerHeader) {
            // WebM/MP4 cannot be decoded without the initialization data in the first chunk.
            containerHeader = event.data
            if (heardVoice) utterance.push(event.data)
            return
          }
          if (heardVoice) utterance.push(event.data)
          else {
            preRoll.push(event.data)
            preRoll = preRoll.slice(-8)
          }
        }
        recorder.onstop = () => {
          if (cancelled || !heardVoice || !utterance.length) return
          const audio = new Blob(utterance, { type: recorder?.mimeType || 'audio/webm' })
          callbacks.current.onUtterance(audio)
        }
        recorder.start(250)
        callbacks.current.onListening()

        const measure = () => {
          if (cancelled || !recorder || recorder.state !== 'recording') return
          analyser.getByteTimeDomainData(samples)
          let energy = 0
          for (const sample of samples) {
            const normalized = (sample - 128) / 128
            energy += normalized * normalized
          }
          const rms = Math.sqrt(energy / samples.length)
          const now = performance.now()
          const threshold = Math.max(MIN_VOICE_THRESHOLD, noiseFloor * NOISE_MULTIPLIER)
          if (rms >= threshold) {
            voiceFrames += 1
            if (!heardVoice) {
              if (voiceFrames >= REQUIRED_VOICE_FRAMES) {
                heardVoice = true
                if (containerHeader) utterance.push(containerHeader)
                utterance.push(...preRoll)
                preRoll = []
              }
            }
            if (heardVoice) lastVoiceAt = now
          } else if (heardVoice && now - lastVoiceAt >= SILENCE_MS) {
            recorder.stop()
            return
          } else {
            voiceFrames = 0
            noiseFloor = (noiseFloor * 0.98) + (rms * 0.02)
          }
          animationFrame = requestAnimationFrame(measure)
        }
        animationFrame = requestAnimationFrame(measure)
      } catch (error) {
        const message = error instanceof DOMException && error.name === 'NotAllowedError'
          ? 'Necesito permiso para usar el micrófono. Pulsa la cara y acepta el permiso.'
          : 'No he podido abrir el micrófono.'
        callbacks.current.onError(message)
      }
    }

    void start()
    return () => {
      cancelled = true
      cancelAnimationFrame(animationFrame)
      if (recorder?.state === 'recording') recorder.stop()
      if (!retainRef.current) {
        stream?.getTracks().forEach((track) => track.stop())
        streamRef.current = undefined
      }
      void context?.close()
    }
  }, [enabled])
}
