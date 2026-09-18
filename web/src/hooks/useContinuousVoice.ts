import { useCallback, useEffect, useRef, useState } from 'react'
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
const MIN_VOICE_THRESHOLD = 0.009
const NOISE_MULTIPLIER = 2.0
const MAX_NOISE_FLOOR = 0.006
const REQUIRED_VOICE_FRAMES = 3
const MIN_CAPTURE_MS = 650
const MIN_SPEECH_MS = 350
const MIN_AUDIO_BYTES = 1200
const PRE_SPEECH_CHUNKS = 8
const MAX_SPEECH_UTTERANCE_MS = 20_000

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
  const manualFinalizeRef = useRef<() => boolean>(() => false)
  const [canFinalize, setCanFinalize] = useState(false)
  const finalizeNow = useCallback(() => manualFinalizeRef.current(), [])

  useEffect(() => {
    if (!enabled) {
      manualFinalizeRef.current = () => false
      setCanFinalize(false)
      return
    }

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
    let speechWatchdog = 0
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
    let activeUtteranceId: string | undefined
    let finalizingUtteranceId: string | undefined

    const log = (event: string, fields: Record<string, unknown> = {}) => {
      console.info('[JARVIS voice]', { utterance_id: machine.utteranceId, event, ...fields })
    }

    const clearCaptureTimers = () => {
      window.clearTimeout(recordingWatchdog)
      window.clearInterval(silenceWatchdog)
      window.clearTimeout(recorderStopWatchdog)
      window.clearTimeout(speechWatchdog)
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
      setCanFinalize(false)
    }

    const stopRecording = (submit: boolean, reason: string) => {
      if (!recorder || recorder.state !== 'recording' || !machine.utteranceId) return
      const utteranceId = machine.utteranceId
      if (!machine.requestFinalize(utteranceId)) return
      finalizingUtteranceId = utteranceId
      activeUtteranceId = undefined
      submitCurrent = submit
      stopReason = reason
      captureStoppedAt = performance.now()
      clearCaptureTimers()
      setCanFinalize(false)
      try { recorder.requestData() } catch { /* Safari may not implement requestData reliably */ }
      recorder.stop()
      recorderStopWatchdog = window.setTimeout(() => {
        if (machine.phase !== 'FINALIZING') return
        log('recording_finalized', { discard_reason: 'recorder_stop_timeout' })
        machine.abort()
        finalizingUtteranceId = undefined
        callbacks.current.onError('La grabación no se cerró correctamente. Sigo escuchando.')
      }, RECORDER_STOP_TIMEOUT_MS)
    }

    const startRecording = () => {
      if (cancelled || pausedRef.current || !recorder || recorder.state !== 'inactive' || machine.phase !== 'IDLE') return
      if (context?.state === 'suspended') void context.resume()
      prepareCaptureMode()
      const utteranceId = crypto.randomUUID()
      if (!machine.start(utteranceId)) return
      activeUtteranceId = utteranceId
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
            speechWatchdog = window.setTimeout(() => {
              stopRecording(true, 'speech_duration_watchdog')
            }, MAX_SPEECH_UTTERANCE_MS)
          } else if (heardVoice) {
            lastVoiceAt = now
          }
        } else if (heardVoice) {
          voiceFrames = 0
          if (now - lastVoiceAt >= SILENCE_MS) stopRecording(true, 'silence_after_voice')
          else if (now - lastVoiceAt < 50) log('silence_started')
        } else {
          voiceFrames = 0
          noiseFloor = Math.min(MAX_NOISE_FLOOR, (noiseFloor * 0.98) + (rms * 0.02))
          if (now - captureStartedAt >= MAX_IDLE_SEGMENT_MS) stopRecording(false, 'idle_segment_rotation')
        }
      }
      animationFrame = requestAnimationFrame(measure)
    }

    const handleStopped = async () => {
      window.clearTimeout(recorderStopWatchdog)
      const utteranceId = finalizingUtteranceId
      if (!utteranceId || machine.phase !== 'FINALIZING') return
      const stoppedAt = captureStoppedAt || performance.now()
      const durationMs = Math.max(0, stoppedAt - captureStartedAt)
      const speechMs = heardVoice ? Math.max(0, lastVoiceAt - speechStartedAt) : 0
      const finalizedChunks = machine.takeFinalizedChunks(utteranceId)
      finalizingUtteranceId = undefined
      const audio = new Blob(finalizedChunks, { type: recorder?.mimeType || 'audio/webm' })
      const manualFinalize = stopReason === 'manual_finalize'
      const effectiveSpeechMs = manualFinalize ? Math.max(speechMs, durationMs) : speechMs
      const discardReason = !submitCurrent ? stopReason
        : !manualFinalize && !heardVoice ? 'no_voice'
          : durationMs < MIN_CAPTURE_MS ? 'audio_too_short'
            : !manualFinalize && speechMs < MIN_SPEECH_MS ? 'speech_too_short'
              : !manualFinalize && maxRms < MIN_VOICE_THRESHOLD ? 'energy_too_low'
                : audio.size < MIN_AUDIO_BYTES ? 'audio_too_small'
                  : undefined
      log('recording_finalized', {
        reason: stopReason,
        manual_finalize: manualFinalize,
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
          { durationMs, speechMs: effectiveSpeechMs, maxRms, utteranceId, manualFinalize },
          {
            processing: () => machine.processing(utteranceId),
            speaking: () => machine.speaking(utteranceId),
          },
        )
      } finally {
        machine.complete(utteranceId)
        setCanFinalize(false)
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
          const utteranceId = finalizingUtteranceId ?? activeUtteranceId
          if (!utteranceId || !machine.addChunk(utteranceId, event.data)) return
          if (!heardVoice && !finalizingUtteranceId) machine.retainRecentChunks(utteranceId, PRE_SPEECH_CHUNKS)
          if (machine.bufferedChunks() > 0) setCanFinalize(true)
        }
        recorder.onstop = () => { void handleStopped() }
        startRecording()
        animationFrame = requestAnimationFrame(measure)
        manualFinalizeRef.current = () => {
          if (!recorder || recorder.state !== 'recording' || machine.phase !== 'LISTENING' || machine.bufferedChunks() === 0) return false
          log('manual_finalize', {
            manual_finalize: true,
            audio_duration: Math.round(performance.now() - captureStartedAt),
            audio_bytes: 'pending_recorder_flush',
          })
          stopRecording(true, 'manual_finalize')
          return true
        }
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
      activeUtteranceId = undefined
      finalizingUtteranceId = undefined
      manualFinalizeRef.current = () => false
      setCanFinalize(false)
      void context?.close()
      // Keep the granted stream for this page session. A full iOS PWA close can
      // trigger a new WebKit permission prompt and cannot be overridden by JS.
    }
  }, [enabled])

  return { canFinalize, finalizeNow }
}
