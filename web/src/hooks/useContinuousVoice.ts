import { useCallback, useEffect, useRef, useState } from 'react'
import type { AudioCaptureMetadata } from '../api/client'
import { VoiceCaptureMachine } from '../voiceCapture'
import { desiredVoiceCaptureMode } from '../speechInterrupt'

export interface VoiceUtteranceLifecycle {
  processing: () => void
}

interface ContinuousVoiceOptions {
  enabled: boolean
  paused: boolean
  conversationState: string
  onListening: () => void
  onUtterance: (audio: Blob, metadata: AudioCaptureMetadata, lifecycle: VoiceUtteranceLifecycle) => Promise<void> | void
  onInterruptUtterance: (audio: Blob, metadata: AudioCaptureMetadata) => Promise<void> | void
  onError: (message: string) => void
}

const configuredSilenceSeconds = Number(import.meta.env.JARVIS_VAD_SILENCE_SECONDS ?? '1.5')
const SILENCE_MS = Number.isFinite(configuredSilenceSeconds)
  ? Math.max(0.5, Math.min(10, configuredSilenceSeconds)) * 1000
  : 1500
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
const MAX_SPEECH_UTTERANCE_MS = 20_000
const INTERRUPT_SILENCE_MS = 650
const MAX_INTERRUPT_SEGMENT_MS = 6_000
const MAX_INTERRUPT_SPEECH_MS = 5_000
const INTERRUPT_PLAYBACK_COOLDOWN_MS = 400

let sharedMicrophone: MediaStream | undefined
let pendingMicrophone: Promise<MediaStream> | undefined
let getUserMediaCallCount = 0
const activeRecorderSessions = new Set<string>()
let interruptCooldownUntil = 0
let lastTtsAudioEndTimestamp = 0

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
  setMicrophoneTracksEnabled(true)
  interruptCooldownUntil = performance.now() + INTERRUPT_PLAYBACK_COOLDOWN_MS
  const audioSessionSupported = setAudioSession('play-and-record')
  console.info('[JARVIS audio session]', { mode: 'speaking_with_interrupt_listener', audio_session_supported: audioSessionSupported })
  return () => {
    lastTtsAudioEndTimestamp = performance.now()
    setAudioSession('play-and-record')
    setMicrophoneTracksEnabled(true)
    console.info('[JARVIS audio session]', {
      mode: 'play-and-record', audio_session_supported: audioSessionSupported,
      tts_audio_end_timestamp: lastTtsAudioEndTimestamp,
    })
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

export function useContinuousVoice({ enabled, paused, conversationState, onListening, onUtterance, onInterruptUtterance, onError }: ContinuousVoiceOptions) {
  const callbacks = useRef({ onListening, onUtterance, onInterruptUtterance, onError })
  const pausedRef = useRef(paused)
  const conversationStateRef = useRef(conversationState)
  callbacks.current = { onListening, onUtterance, onInterruptUtterance, onError }
  pausedRef.current = paused
  conversationStateRef.current = conversationState
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
    const recorderSessionId = crypto.randomUUID()
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
    let lastCaptureIgnoredReason = ''
    let captureMode: 'normal' | 'interrupt' = 'normal'
    let firstAudioFrameLogged = false

    const log = (event: string, fields: Record<string, unknown> = {}) => {
      console.info('[JARVIS voice]', {
        utterance_id: machine.utteranceId,
        event,
        audio_state: machine.phase,
        conversation_state: conversationStateRef.current.toUpperCase(),
        mic_active: Boolean(sharedMicrophone?.getAudioTracks().some((track) => track.readyState === 'live' && track.enabled)),
        active_media_recorders: activeRecorderSessions.size,
        recorder_state: recorder?.state ?? 'uninitialized',
        capture_mode: captureMode,
        ...fields,
      })
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
      const stateFrom = machine.phase
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
      activeRecorderSessions.delete(recorderSessionId)
      if (submit && captureMode === 'normal') setMicrophoneTracksEnabled(false)
      log('audio_state_changed', {
        state_from: stateFrom, state_to: machine.phase, speech_detected: heardVoice,
        finalize_reason: reason, capture_ignored_reason: submit ? 'processing_started' : reason,
      })
      recorderStopWatchdog = window.setTimeout(() => {
        if (machine.phase !== 'FINALIZING') return
        if (submitCurrent && heardVoice && machine.bufferedChunks() > 0) {
          log('finalizing_watchdog', {
            state_from: 'FINALIZING', state_to: 'TRANSCRIBING', speech_detected: true,
            finalize_reason: `${reason}_watchdog`,
          })
          void handleStopped()
        } else {
          log('recording_finalized', { discard_reason: 'recorder_stop_timeout', speech_detected: heardVoice })
          machine.abort()
          finalizingUtteranceId = undefined
          callbacks.current.onError('La grabación no se cerró correctamente. Sigo escuchando.')
        }
      }, RECORDER_STOP_TIMEOUT_MS)
    }

    const startRecording = (mode: 'normal' | 'interrupt') => {
      const wrongPauseState = mode === 'normal' ? pausedRef.current : !pausedRef.current
      if (cancelled || wrongPauseState || !recorder || recorder.state !== 'inactive' || machine.phase !== 'IDLE') return
      if (activeRecorderSessions.size && !activeRecorderSessions.has(recorderSessionId)) {
        if (lastCaptureIgnoredReason !== 'another_media_recorder_active') {
          lastCaptureIgnoredReason = 'another_media_recorder_active'
          log('capture_ignored', { capture_ignored_reason: lastCaptureIgnoredReason })
        }
        return
      }
      if (context?.state === 'suspended') void context.resume()
      prepareCaptureMode()
      const utteranceId = crypto.randomUUID()
      if (!machine.start(utteranceId)) return
      captureMode = mode
      activeUtteranceId = utteranceId
      resetMetrics()
      activeRecorderSessions.add(recorderSessionId)
      recorder.start(250)
      const listenerArmedTimestamp = performance.now()
      firstAudioFrameLogged = false
      lastCaptureIgnoredReason = ''
      log('recording_started', {
        listener_armed_timestamp: listenerArmedTimestamp,
        tts_end_to_listener_armed_ms: lastTtsAudioEndTimestamp
          ? Number((listenerArmedTimestamp - lastTtsAudioEndTimestamp).toFixed(1)) : undefined,
      })
      if (captureMode === 'normal') callbacks.current.onListening()
      recordingWatchdog = window.setTimeout(() => {
        stopRecording(heardVoice, captureMode === 'interrupt' ? 'interrupt_segment_limit' : heardVoice ? 'max_recording_duration' : 'max_recording_without_voice')
      }, captureMode === 'interrupt' ? MAX_INTERRUPT_SEGMENT_MS : MAX_RECORDING_MS)
      silenceWatchdog = window.setInterval(() => {
        const silenceMs = captureMode === 'interrupt' ? INTERRUPT_SILENCE_MS : SILENCE_MS
        if (heardVoice && performance.now() - lastVoiceAt >= silenceMs) stopRecording(true, 'silence_watchdog')
      }, 250)
    }

    const measure = () => {
      if (cancelled) return
      const desiredMode = desiredVoiceCaptureMode(pausedRef.current, conversationStateRef.current)
      if (machine.phase === 'LISTENING' && captureMode !== desiredMode) {
        stopRecording(false, desiredMode ? 'capture_mode_changed' : 'paused_before_submission')
      } else if (!desiredMode && machine.phase === 'IDLE') {
        if (lastCaptureIgnoredReason !== 'conversation_busy') {
          lastCaptureIgnoredReason = 'conversation_busy'
          log('capture_ignored', { capture_ignored_reason: lastCaptureIgnoredReason })
        }
      } else if (desiredMode && machine.phase === 'IDLE') {
        startRecording(desiredMode)
      } else if (machine.phase === 'LISTENING' && recorder?.state === 'recording' && analyser && samples) {
        if (!firstAudioFrameLogged) {
          firstAudioFrameLogged = true
          log('first_audio_frame', { first_audio_frame_timestamp: performance.now() })
        }
        analyser.getByteTimeDomainData(samples)
        let energy = 0
        for (const sample of samples) {
          const normalized = (sample - 128) / 128
          energy += normalized * normalized
        }
        const rms = Math.sqrt(energy / samples.length)
        const now = performance.now()
        if (captureMode === 'interrupt' && now < interruptCooldownUntil) {
          voiceFrames = 0
          animationFrame = requestAnimationFrame(measure)
          return
        }
        maxRms = Math.max(maxRms, rms)
        threshold = Math.max(MIN_VOICE_THRESHOLD, noiseFloor * NOISE_MULTIPLIER)
        if (rms >= threshold) {
          voiceFrames += 1
          if (!heardVoice && voiceFrames >= REQUIRED_VOICE_FRAMES) {
            heardVoice = true
            speechStartedAt = now
            lastVoiceAt = now
            log('speech_detected', { rms: Number(rms.toFixed(4)), vad_speech_start_timestamp: now })
            speechWatchdog = window.setTimeout(() => {
              stopRecording(true, 'speech_duration_watchdog')
            }, captureMode === 'interrupt' ? MAX_INTERRUPT_SPEECH_MS : MAX_SPEECH_UTTERANCE_MS)
          } else if (heardVoice) {
            lastVoiceAt = now
          }
        } else if (heardVoice) {
          voiceFrames = 0
          const silenceMs = captureMode === 'interrupt' ? INTERRUPT_SILENCE_MS : SILENCE_MS
          if (now - lastVoiceAt >= silenceMs) stopRecording(true, 'silence_after_voice')
          else if (now - lastVoiceAt < 50) log('silence_started')
        } else {
          voiceFrames = 0
          noiseFloor = Math.min(MAX_NOISE_FLOOR, (noiseFloor * 0.98) + (rms * 0.02))
          const idleLimit = captureMode === 'interrupt' ? MAX_INTERRUPT_SEGMENT_MS : MAX_IDLE_SEGMENT_MS
          if (now - captureStartedAt >= idleLimit) stopRecording(false, 'idle_segment_rotation')
        }
      }
      animationFrame = requestAnimationFrame(measure)
    }

    const handleStopped = async () => {
      window.clearTimeout(recorderStopWatchdog)
      const utteranceId = finalizingUtteranceId
      if (!utteranceId || machine.phase !== 'FINALIZING') return
      const stoppedAt = captureStoppedAt || performance.now()
      const finalizedCaptureMode = captureMode
      const durationMs = Math.max(0, stoppedAt - captureStartedAt)
      const speechMs = heardVoice ? Math.max(0, lastVoiceAt - speechStartedAt) : 0
      const stateFrom = machine.phase
      const finalizedChunks = machine.takeFinalizedChunks(utteranceId)
      log('audio_state_changed', {
        state_from: stateFrom, state_to: machine.phase, speech_detected: heardVoice,
        finalize_reason: stopReason,
      })
      finalizingUtteranceId = undefined
      const audio = new Blob(finalizedChunks, { type: recorder?.mimeType || 'audio/webm' })
      const manualFinalize = stopReason === 'manual_finalize'
      const effectiveSpeechMs = manualFinalize ? Math.max(speechMs, durationMs) : speechMs
      const minimumCaptureMs = finalizedCaptureMode === 'interrupt' ? 500 : MIN_CAPTURE_MS
      const minimumSpeechMs = finalizedCaptureMode === 'interrupt' ? 300 : MIN_SPEECH_MS
      const discardReason = !submitCurrent ? stopReason
        : !manualFinalize && !heardVoice ? 'no_voice'
          : durationMs < minimumCaptureMs ? 'audio_too_short'
            : !manualFinalize && speechMs < minimumSpeechMs ? 'speech_too_short'
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

      log('transcription_started', { speech_detected: heardVoice, finalize_reason: stopReason })
      try {
        const metadata = { durationMs, speechMs: effectiveSpeechMs, maxRms, utteranceId, manualFinalize }
        if (finalizedCaptureMode === 'interrupt') {
          machine.processing(utteranceId)
          await callbacks.current.onInterruptUtterance(audio, metadata)
        } else {
          await callbacks.current.onUtterance(
            audio,
            metadata,
            {
              processing: () => {
                const from = machine.phase
                machine.processing(utteranceId)
                log('processing_started', { state_from: from, state_to: machine.phase, speech_detected: heardVoice, finalize_reason: stopReason })
              },
            },
          )
        }
      } finally {
        machine.complete(utteranceId)
        log('audio_state_changed', { capture_ignored_reason: 'none' })
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
          if (captureMode === 'normal' && machine.bufferedChunks() > 0) setCanFinalize(true)
        }
        recorder.onstop = () => { void handleStopped() }
        startRecording('normal')
        animationFrame = requestAnimationFrame(measure)
        manualFinalizeRef.current = () => {
          if (captureMode !== 'normal' || !recorder || recorder.state !== 'recording' || machine.phase !== 'LISTENING' || machine.bufferedChunks() === 0) return false
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
      activeRecorderSessions.delete(recorderSessionId)
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
