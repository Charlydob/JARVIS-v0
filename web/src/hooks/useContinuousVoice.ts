import { useEffect, useRef } from 'react'

interface ContinuousVoiceOptions {
  enabled: boolean
  paused: boolean
  onListening: () => void
  onUtterance: (audio: Blob) => Promise<void> | void
  onError: (message: string) => void
}

const SILENCE_MS = 3000
const MIN_VOICE_THRESHOLD = 0.012
const NOISE_MULTIPLIER = 2.8
const REQUIRED_VOICE_FRAMES = 3

export function useContinuousVoice({ enabled, paused, onListening, onUtterance, onError }: ContinuousVoiceOptions) {
  const callbacks = useRef({ onListening, onUtterance, onError })
  const pausedRef = useRef(paused)
  callbacks.current = { onListening, onUtterance, onError }
  pausedRef.current = paused

  useEffect(() => {
    if (!enabled) return

    let cancelled = false
    let animationFrame = 0
    let stream: MediaStream | undefined
    let context: AudioContext | undefined
    let recorder: MediaRecorder | undefined
    let analyser: AnalyserNode | undefined
    let samples: Uint8Array | undefined
    let stopping = false
    let submitCurrent = false
    let waitingForTurn = false
    let heardVoice = false
    let lastVoiceAt = 0
    let noiseFloor = 0.006
    let voiceFrames = 0
    let containerHeader: Blob | undefined
    let preRoll: Blob[] = []
    let utterance: Blob[] = []

    const resetCapture = () => {
      submitCurrent = false
      heardVoice = false
      lastVoiceAt = 0
      noiseFloor = 0.006
      voiceFrames = 0
      containerHeader = undefined
      preRoll = []
      utterance = []
    }

    const startRecording = () => {
      if (cancelled || pausedRef.current || !recorder || recorder.state !== 'inactive') return
      if (context?.state === 'suspended') void context.resume()
      resetCapture()
      recorder.start(250)
      callbacks.current.onListening()
    }

    const stopRecording = (submit: boolean) => {
      if (!recorder || recorder.state !== 'recording' || stopping) return
      submitCurrent = submit
      stopping = true
      recorder.stop()
    }

    const measure = () => {
      if (cancelled) return
      if (pausedRef.current) {
        stopRecording(false)
        animationFrame = requestAnimationFrame(measure)
        return
      }
      if (waitingForTurn) {
        animationFrame = requestAnimationFrame(measure)
        return
      }
      if (!recorder || recorder.state === 'inactive') {
        startRecording()
        animationFrame = requestAnimationFrame(measure)
        return
      }
      if (recorder.state !== 'recording' || !analyser || !samples) {
        animationFrame = requestAnimationFrame(measure)
        return
      }

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
        if (!heardVoice && voiceFrames >= REQUIRED_VOICE_FRAMES) {
          heardVoice = true
          if (containerHeader) utterance.push(containerHeader)
          utterance.push(...preRoll)
          preRoll = []
        }
        if (heardVoice) lastVoiceAt = now
      } else if (heardVoice && now - lastVoiceAt >= SILENCE_MS) {
        stopRecording(true)
      } else {
        voiceFrames = 0
        noiseFloor = (noiseFloor * 0.98) + (rms * 0.02)
      }
      animationFrame = requestAnimationFrame(measure)
    }

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
        analyser = context.createAnalyser()
        analyser.fftSize = 1024
        source.connect(analyser)
        samples = new Uint8Array(analyser.fftSize)

        const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : ''
        recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
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
          stopping = false
          if (cancelled || !submitCurrent || !heardVoice || !utterance.length) return
          const audio = new Blob(utterance, { type: recorder?.mimeType || 'audio/webm' })
          waitingForTurn = true
          Promise.resolve(callbacks.current.onUtterance(audio)).finally(() => {
            waitingForTurn = false
          })
        }

        startRecording()
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
