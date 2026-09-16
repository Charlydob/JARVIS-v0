import { useEffect, useRef } from 'react'

interface ContinuousVoiceOptions {
  enabled: boolean
  onListening: () => void
  onUtterance: (audio: Blob) => void
  onError: (message: string) => void
}

const SILENCE_MS = 3000
const VOICE_THRESHOLD = 0.025

export function useContinuousVoice({ enabled, onListening, onUtterance, onError }: ContinuousVoiceOptions) {
  const callbacks = useRef({ onListening, onUtterance, onError })
  callbacks.current = { onListening, onUtterance, onError }

  useEffect(() => {
    if (!enabled) return

    let cancelled = false
    let animationFrame = 0
    let stream: MediaStream | undefined
    let context: AudioContext | undefined
    let recorder: MediaRecorder | undefined

    const start = async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
        })
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
        let preRoll: Blob[] = []
        const utterance: Blob[] = []

        recorder.ondataavailable = (event) => {
          if (!event.data.size) return
          if (heardVoice) utterance.push(event.data)
          else {
            preRoll.push(event.data)
            preRoll = preRoll.slice(-8)
          }
        }
        recorder.onstop = () => {
          if (cancelled || !heardVoice || !utterance.length) return
          const audio = new Blob([...preRoll, ...utterance], { type: recorder?.mimeType || 'audio/webm' })
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
          if (rms >= VOICE_THRESHOLD) {
            if (!heardVoice) {
              heardVoice = true
              utterance.push(...preRoll)
              preRoll = []
            }
            lastVoiceAt = now
          } else if (heardVoice && now - lastVoiceAt >= SILENCE_MS) {
            recorder.stop()
            return
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
      stream?.getTracks().forEach((track) => track.stop())
      void context?.close()
    }
  }, [enabled])
}
