import { useEffect, useRef } from 'react'
import type { AudioCaptureMetadata } from '../api/client'

interface ContinuousVoiceOptions {
  enabled: boolean
  paused: boolean
  onListening: () => void
  onUtterance: (audio: Blob, metadata: AudioCaptureMetadata) => Promise<void> | void
  onError: (message: string) => void
}

const SILENCE_MS = 3000
const MAX_IDLE_SEGMENT_MS = 15_000
const MIN_VOICE_THRESHOLD = 0.012
const NOISE_MULTIPLIER = 2.8
const REQUIRED_VOICE_FRAMES = 3
const MIN_CAPTURE_MS = 650
const MIN_SPEECH_MS = 350
const MIN_AUDIO_BYTES = 1200

let sharedMicrophone: MediaStream | undefined
let pendingMicrophone: Promise<MediaStream> | undefined

async function acquireMicrophone(): Promise<MediaStream> {
  if (sharedMicrophone?.getAudioTracks().some((track) => track.readyState === 'live')) return sharedMicrophone
  if (!pendingMicrophone) {
    pendingMicrophone = navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
    }).then((stream) => {
      sharedMicrophone = stream
      return stream
    }).finally(() => { pendingMicrophone = undefined })
  }
  return pendingMicrophone
}

function releaseMicrophone() {
  sharedMicrophone?.getTracks().forEach((track) => track.stop())
  sharedMicrophone = undefined
}

if (typeof window !== 'undefined') window.addEventListener('pagehide', releaseMicrophone)

export function useContinuousVoice({ enabled, paused, onListening, onUtterance, onError }: ContinuousVoiceOptions) {
  const callbacks = useRef({ onListening, onUtterance, onError })
  const pausedRef = useRef(paused)
  callbacks.current = { onListening, onUtterance, onError }
  pausedRef.current = paused

  useEffect(() => {
    if (!enabled) return

    let cancelled = false
    let animationFrame = 0
    let context: AudioContext | undefined
    let recorder: MediaRecorder | undefined
    let analyser: AnalyserNode | undefined
    let samples: Uint8Array | undefined
    let stopping = false
    let submitCurrent = false
    let stopReason = 'unknown'
    let waitingForTurn = false
    let heardVoice = false
    let lastVoiceAt = 0
    let speechStartedAt = 0
    let captureStartedAt = 0
    let captureStoppedAt = 0
    let noiseFloor = 0.006
    let threshold = MIN_VOICE_THRESHOLD
    let maxRms = 0
    let voiceFrames = 0
    let chunks: Blob[] = []

    const resetCapture = () => {
      submitCurrent = false
      stopReason = 'unknown'
      heardVoice = false
      lastVoiceAt = 0
      speechStartedAt = 0
      captureStartedAt = performance.now()
      captureStoppedAt = 0
      noiseFloor = 0.006
      threshold = MIN_VOICE_THRESHOLD
      maxRms = 0
      voiceFrames = 0
      chunks = []
    }

    const startRecording = () => {
      if (cancelled || stopping || pausedRef.current || !recorder || recorder.state !== 'inactive') return
      if (context?.state === 'suspended') void context.resume()
      resetCapture()
      recorder.start(250)
      callbacks.current.onListening()
    }

    const stopRecording = (submit: boolean, reason: string) => {
      if (!recorder || recorder.state !== 'recording' || stopping) return
      submitCurrent = submit
      stopReason = reason
      captureStoppedAt = performance.now()
      stopping = true
      recorder.stop()
    }

    const measure = () => {
      if (cancelled) return
      if (pausedRef.current) {
        stopRecording(false, 'paused_before_submission')
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
      maxRms = Math.max(maxRms, rms)
      threshold = Math.max(MIN_VOICE_THRESHOLD, noiseFloor * NOISE_MULTIPLIER)
      if (rms >= threshold) {
        voiceFrames += 1
        if (!heardVoice && voiceFrames >= REQUIRED_VOICE_FRAMES) {
          heardVoice = true
          speechStartedAt = now
        }
        if (heardVoice) lastVoiceAt = now
      } else if (heardVoice && now - lastVoiceAt >= SILENCE_MS) {
        stopRecording(true, 'silence_after_voice')
      } else {
        voiceFrames = 0
        noiseFloor = (noiseFloor * 0.98) + (rms * 0.02)
        if (!heardVoice && now - captureStartedAt >= MAX_IDLE_SEGMENT_MS) {
          stopRecording(false, 'idle_segment_rotation')
        }
      }
      animationFrame = requestAnimationFrame(measure)
    }

    const start = async () => {
      try {
        const stream = await acquireMicrophone()
        if (cancelled) return

        context = new AudioContext()
        const source = context.createMediaStreamSource(stream)
        analyser = context.createAnalyser()
        analyser.fftSize = 1024
        source.connect(analyser)
        samples = new Uint8Array(analyser.fftSize)

        const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
          ? 'audio/webm;codecs=opus'
          : MediaRecorder.isTypeSupported('audio/mp4') ? 'audio/mp4' : ''
        recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
        recorder.ondataavailable = (event) => {
          if (event.data.size) chunks.push(event.data)
        }
        recorder.onstop = () => {
          stopping = false
          const stoppedAt = captureStoppedAt || performance.now()
          const durationMs = Math.max(0, stoppedAt - captureStartedAt)
          const speechMs = heardVoice ? Math.max(0, lastVoiceAt - speechStartedAt) : 0
          const audio = new Blob(chunks, { type: recorder?.mimeType || 'audio/webm' })
          const discardReason = !submitCurrent ? stopReason
            : !heardVoice ? 'no_voice'
              : durationMs < MIN_CAPTURE_MS ? 'audio_too_short'
                : speechMs < MIN_SPEECH_MS ? 'speech_too_short'
                  : maxRms < MIN_VOICE_THRESHOLD ? 'energy_too_low'
                    : audio.size < MIN_AUDIO_BYTES ? 'audio_too_small'
                      : undefined
          console.info('[JARVIS audio capture]', {
            reason: stopReason,
            durationMs: Math.round(durationMs),
            speechMs: Math.round(speechMs),
            bytes: audio.size,
            mimeType: audio.type,
            maxRms: Number(maxRms.toFixed(4)),
            threshold: Number(threshold.toFixed(4)),
            discardReason: discardReason ?? 'none',
          })
          if (cancelled || discardReason) return
          waitingForTurn = true
          Promise.resolve(callbacks.current.onUtterance(audio, { durationMs, speechMs, maxRms })).finally(() => {
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
      if (recorder?.state === 'recording') stopRecording(false, 'listener_suspended')
      void context?.close()
      // Keep the granted stream for this page session so transient Core/view
      // changes do not trigger another browser permission request.
    }
  }, [enabled])
}
