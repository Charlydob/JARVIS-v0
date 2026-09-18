import { useEffect, useRef } from 'react'
import type { AudioCaptureMetadata } from '../api/client'
import { VoiceCaptureMachine } from '../voiceCapture'

export interface VoiceUtteranceLifecycle {
  processing: () => void
  speaking: () => void
}

interface ContinuousVoiceOptions {
  enabled: boolean
  paused: boolean
  onListening: () => void
  onUtterance: (audio: Blob, metadata: AudioCaptureMetadata, lifecycle: VoiceUtteranceLifecycle) => Promise<void> | void
  onError: (message: string) => void
}

const SILENCE_MS = 3000
const MAX_RECORDING_MS = 30_000
const MAX_IDLE_SEGMENT_MS = 15_000
const RECORDER_STOP_TIMEOUT_MS = 4000
const MIN_VOICE_THRESHOLD = 0.012
const NOISE_MULTIPLIER = 2.8
const REQUIRED_VOICE_FRAMES = 3
const MIN_CAPTURE_MS = 650
const MIN_SPEECH_MS = 350
const MIN_AUDIO_BYTES = 1200

let sharedMicrophone: MediaStream | undefined
let pendingMicrophone: Promise<MediaStream> | undefined
let getUserMediaCallCount = 0

type AudioSessionNavigator = Navigator & { audioSession?: { type: string } }

function setAudioSession(type: 'playback' | 'play-and-record' | 'auto') {
  const session = (navigator as AudioSessionNavigator).audioSession
  if (!session) return false
  try {
    session.type = type
    return true
  } catch {
    return false
  }
}

function setMicrophoneTracksEnabled(enabled: boolean) {
  sharedMicrophone?.getAudioTracks().forEach((track) => { track.enabled = enabled })
}

function prepareCaptureMode() {
  setMicrophoneTracksEnabled(true)
  setAudioSession('play-and-record')
}

export function beginSpeechPlayback(): () => void {
  setMicrophoneTracksEnabled(false)
  const audioSessionSupported = setAudioSession('playback')
  console.info('[JARVIS audio session]', { mode: 'playback', audio_session_supported: audioSessionSupported })
  return () => {
    setAudioSession('play-and-record')
    setMicrophoneTracksEnabled(true)
    console.info('[JARVIS audio session]', { mode: 'play-and-record', audio_session_supported: audioSessionSupported })
  }
}

async function acquireMicrophone(reason: string): Promise<MediaStream> {
  if (sharedMicrophone?.getAudioTracks().some((track) => track.readyState === 'live')) {
    console.info('[JARVIS microphone]', { getUserMedia_call_count: getUserMediaCallCount, reason, stream_reused: true, stream_recreated: false })
    return sharedMicrophone
  }
  if (pendingMicrophone) {
    console.info('[JARVIS microphone]', { getUserMedia_call_count: getUserMediaCallCount, reason, stream_reused: true, stream_recreated: false })
    return pendingMicrophone
  }
  getUserMediaCallCount += 1
  console.info('[JARVIS microphone]', { getUserMedia_call_count: getUserMediaCallCount, reason, stream_reused: false, stream_recreated: true })
  pendingMicrophone = navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
  }).then((stream) => {
    sharedMicrophone = stream
    stream.getAudioTracks().forEach((track) => track.addEventListener('ended', () => {
      if (sharedMicrophone === stream) sharedMicrophone = undefined
    }, { once: true }))
    return stream
  }).finally(() => { pendingMicrophone = undefined })
  return pendingMicrophone
}

function releaseMicrophone() {
  sharedMicrophone?.getTracks().forEach((track) => track.stop())
  sharedMicrophone = undefined
  setAudioSession('auto')
}

if (typeof window !== 'undefined') window.addEventListener('pagehide', releaseMicrophone)

export function useContinuousVoice({ enabled, paused, onListening, onUtterance, onError }: ContinuousVoiceOptions) {
  const callbacks = useRef({ onListening, onUtterance, onError })
  const pausedRef = useRef(paused)
  callbacks.current = { onListening, onUtterance, onError }
  pausedRef.current = paused

  useEffect(() => {
    if (!enabled) return

    const machine = new VoiceCaptureMachine()
    let cancelled = false
    let animationFrame = 0
    let context: AudioContext | undefined
    let recorder: MediaRecorder | undefined
    let analyser: AnalyserNode | undefined
    let samples: Uint8Array | undefined
    let recordingWatchdog = 0
    let silenceWatchdog = 0
    let recorderStopWatchdog = 0
    let submitCurrent = false
    let stopReason = 'unknown'
    let heardVoice = false
    let lastVoiceAt = 0
    let speechStartedAt = 0
    let captureStartedAt = 0
    let captureStoppedAt = 0
    let noiseFloor = 0.006
    let threshold = MIN_VOICE_THRESHOLD
    let maxRms = 0
    let voiceFrames = 0

    const log = (event: string, fields: Record<string, unknown> = {}) => {
      console.info('[JARVIS voice]', { utterance_id: machine.utteranceId, event, ...fields })
    }

    const clearCaptureTimers = () => {
      window.clearTimeout(recordingWatchdog)
      window.clearInterval(silenceWatchdog)
      window.clearTimeout(recorderStopWatchdog)
    }

    const resetMetrics = () => {
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
    }

    const stopRecording = (submit: boolean, reason: string) => {
      if (!recorder || recorder.state !== 'recording' || !machine.utteranceId) return
      const utteranceId = machine.utteranceId
      if (!machine.requestFinalize(utteranceId)) return
      submitCurrent = submit
      stopReason = reason
      captureStoppedAt = performance.now()
      clearCaptureTimers()
      try { recorder.requestData() } catch { /* Safari may not implement requestData reliably */ }
      recorder.stop()
      recorderStopWatchdog = window.setTimeout(() => {
        if (machine.phase !== 'FINALIZING') return
        log('recording_finalized', { discard_reason: 'recorder_stop_timeout' })
        machine.abort()
        callbacks.current.onError('La grabación no se cerró correctamente. Sigo escuchando.')
      }, RECORDER_STOP_TIMEOUT_MS)
    }

    const startRecording = () => {
      if (cancelled || pausedRef.current || !recorder || recorder.state !== 'inactive' || machine.phase !== 'IDLE') return
      if (context?.state === 'suspended') void context.resume()
      prepareCaptureMode()
      const utteranceId = crypto.randomUUID()
      if (!machine.start(utteranceId)) return
      resetMetrics()
      recorder.start(250)
      log('recording_started')
      callbacks.current.onListening()
      recordingWatchdog = window.setTimeout(() => {
        stopRecording(heardVoice, heardVoice ? 'max_recording_duration' : 'max_recording_without_voice')
      }, MAX_RECORDING_MS)
      silenceWatchdog = window.setInterval(() => {
        if (heardVoice && performance.now() - lastVoiceAt >= SILENCE_MS) stopRecording(true, 'silence_watchdog')
      }, 250)
    }

    const measure = () => {
      if (cancelled) return
      if (pausedRef.current && machine.phase === 'LISTENING') {
        stopRecording(false, 'paused_before_submission')
      } else if (machine.phase === 'IDLE') {
        startRecording()
      } else if (machine.phase === 'LISTENING' && recorder?.state === 'recording' && analyser && samples) {
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
            lastVoiceAt = now
            log('speech_detected', { rms: Number(rms.toFixed(4)) })
          } else if (heardVoice) {
            lastVoiceAt = now
          }
        } else if (heardVoice) {
          voiceFrames = 0
          if (now - lastVoiceAt >= SILENCE_MS) stopRecording(true, 'silence_after_voice')
          else if (now - lastVoiceAt < 50) log('silence_started')
        } else {
          voiceFrames = 0
          noiseFloor = (noiseFloor * 0.98) + (rms * 0.02)
          if (now - captureStartedAt >= MAX_IDLE_SEGMENT_MS) stopRecording(false, 'idle_segment_rotation')
        }
      }
      animationFrame = requestAnimationFrame(measure)
    }

    const handleStopped = async () => {
      window.clearTimeout(recorderStopWatchdog)
      const utteranceId = machine.utteranceId
      if (!utteranceId || machine.phase !== 'FINALIZING') return
      const stoppedAt = captureStoppedAt || performance.now()
      const durationMs = Math.max(0, stoppedAt - captureStartedAt)
      const speechMs = heardVoice ? Math.max(0, lastVoiceAt - speechStartedAt) : 0
      const finalizedChunks = machine.takeFinalizedChunks(utteranceId)
      const audio = new Blob(finalizedChunks, { type: recorder?.mimeType || 'audio/webm' })
      const discardReason = !submitCurrent ? stopReason
        : !heardVoice ? 'no_voice'
          : durationMs < MIN_CAPTURE_MS ? 'audio_too_short'
            : speechMs < MIN_SPEECH_MS ? 'speech_too_short'
              : maxRms < MIN_VOICE_THRESHOLD ? 'energy_too_low'
                : audio.size < MIN_AUDIO_BYTES ? 'audio_too_small'
                  : undefined
      log('recording_finalized', {
        reason: stopReason,
        audio_duration: Math.round(durationMs),
        speech_ms: Math.round(speechMs),
        audio_bytes: audio.size,
        rms: Number(maxRms.toFixed(4)),
        discard_reason: discardReason ?? 'none',
      })
      if (cancelled || discardReason) {
        machine.complete(utteranceId)
        return
      }

      setMicrophoneTracksEnabled(false)
      log('transcription_started')
      try {
        await callbacks.current.onUtterance(
          audio,
          { durationMs, speechMs, maxRms, utteranceId },
          {
            processing: () => machine.processing(utteranceId),
            speaking: () => machine.speaking(utteranceId),
          },
        )
      } finally {
        machine.complete(utteranceId)
        if (!cancelled) prepareCaptureMode()
      }
    }

    const start = async () => {
      try {
        const stream = await acquireMicrophone('continuous_voice_start')
        if (cancelled) return
        prepareCaptureMode()
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
          if (machine.utteranceId) machine.addChunk(machine.utteranceId, event.data)
        }
        recorder.onstop = () => { void handleStopped() }
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
      clearCaptureTimers()
      if (recorder) {
        recorder.ondataavailable = null
        recorder.onstop = null
        if (recorder.state === 'recording') recorder.stop()
      }
      machine.abort()
      void context?.close()
      // Keep the granted stream for this page session. A full iOS PWA close can
      // trigger a new WebKit permission prompt and cannot be overridden by JS.
    }
  }, [enabled])
}
