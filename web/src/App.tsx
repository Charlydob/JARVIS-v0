import { FormEvent, useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { ArrowLeft, Check, Cookie, Copy, History, Menu, Send, Volume2, VolumeX, X } from 'lucide-react'
import {
  getHistory,
  getStats,
  getStatus,
  ConversationStats,
  HistoryItem,
  sendFeedback,
  streamMessage,
  synthesizeSpeech,
  transcribeAudio
} from './api/client'
import type { UserLocation } from './api/client'
import { JarvisFace } from './components/jarvis-face/JarvisFace'
import { beginSpeechPlayback, useContinuousVoice } from './hooks/useContinuousVoice'
import type { VoiceUtteranceLifecycle } from './hooks/useContinuousVoice'
import type { AudioCaptureMetadata } from './api/client'
import { JarvisState, stateLabels, transition } from './state/machine'
import { takeSpeechSegments } from './speech'
import { PrefetchedSpeechQueue } from './speechQueue'
import { parseSpeechInterrupt } from './speechInterrupt'
import { copyPlainText, formatHistorySelection } from './historyExport'

type View = 'face' | 'dashboard'

function WhipIcon({ size = 15 }: { size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M4 20l4-4" /><path d="M7 17c6 2 13-2 12-8-.5-3-4-5-7-3-2 1-2 4 0 5 2 1 5 0 7-2" /><path d="M3 19l2 2" /></svg>
}

function sameLocalDay(left: Date, right: Date) {
  return left.getFullYear() === right.getFullYear() && left.getMonth() === right.getMonth() && left.getDate() === right.getDate()
}

function historyDayLabel(date: Date) {
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)
  if (sameLocalDay(date, today)) return 'Hoy'
  if (sameLocalDay(date, yesterday)) return 'Ayer'
  return date.toLocaleDateString('es-ES', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
}

function cleanAssistantText(value: string) {
  return value.replace(/^\s*assistant\s*:?\s*/i, '').trim()
}

const speechAudio = new Audio()
speechAudio.preload = 'auto'
let speechUnlocked = false
let activeSpeechCancellation: (() => void) | undefined

function cancelSpeechPlayback() {
  activeSpeechCancellation?.()
}

function silentWav(): Blob {
  const sampleRate = 8000
  const samples = 800
  const buffer = new ArrayBuffer(44 + samples)
  const view = new DataView(buffer)
  const write = (offset: number, value: string) => [...value].forEach((letter, index) => view.setUint8(offset + index, letter.charCodeAt(0)))
  write(0, 'RIFF'); view.setUint32(4, 36 + samples, true); write(8, 'WAVE'); write(12, 'fmt ')
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate, true); view.setUint16(32, 1, true); view.setUint16(34, 8, true)
  write(36, 'data'); view.setUint32(40, samples, true)
  for (let index = 44; index < 44 + samples; index += 1) view.setUint8(index, 128)
  return new Blob([buffer], { type: 'audio/wav' })
}

async function unlockSpeech(): Promise<boolean> {
  if (speechUnlocked) return true
  const url = URL.createObjectURL(silentWav())
  speechAudio.src = url
  speechAudio.volume = 0.01
  try {
    await speechAudio.play()
    speechAudio.pause()
    speechAudio.currentTime = 0
    speechAudio.volume = 1
    speechUnlocked = true
    return true
  } catch {
    return false
  } finally {
    URL.revokeObjectURL(url)
  }
}

function playAudio(blob: Blob, onPlayback: (playing: boolean) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob)
    const restoreCapture = beginSpeechPlayback()
    let settled = false
    const finish = (error?: unknown) => {
      if (settled) return
      settled = true
      if (activeSpeechCancellation === cancel) activeSpeechCancellation = undefined
      speechAudio.onended = null
      speechAudio.onerror = null
      onPlayback(false)
      restoreCapture()
      URL.revokeObjectURL(url)
      if (error) reject(error)
      else resolve()
    }
    const cancel = () => {
      speechAudio.pause()
      speechAudio.removeAttribute('src')
      speechAudio.load()
      finish()
    }
    activeSpeechCancellation = cancel
    speechAudio.pause()
    speechAudio.src = url
    speechAudio.volume = 1
    speechAudio.onended = () => finish()
    speechAudio.onerror = () => { speechUnlocked = false; finish(new Error('No se pudo reproducir la voz')) }
    speechAudio.play()
      .then(() => { if (!settled) onPlayback(true) })
      .catch((error) => {
        if (settled) return
        speechUnlocked = false
        finish(error)
      })
  })
}

export default function App() {
  const [state, dispatch] = useReducer(transition, 'sleeping' as JarvisState)
  const [view, setView] = useState<View>('face')
  const [menuOpen, setMenuOpen] = useState(false)
  const [muted, setMuted] = useState(() => localStorage.getItem('jarvis-muted') === 'true')
  const [soundEnabled, setSoundEnabled] = useState(() => localStorage.getItem('jarvis-sound') !== 'false')
  const [voiceReady, setVoiceReady] = useState(false)
  const [audioPlaying, setAudioPlaying] = useState(false)
  const [location, setLocation] = useState<UserLocation>()
  const [coreOnline, setCoreOnline] = useState(false)
  const [notice, setNotice] = useState('Conectando con el Core…')
  const [input, setInput] = useState('')
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [stats, setStats] = useState<ConversationStats>({ messages: 0, positives: 0, negatives: 0 })
  const [latestResponse, setLatestResponse] = useState<{ id: string; rating: 'good' | 'bad' | null } | null>(null)
  const [badMessage, setBadMessage] = useState<string | null>(null)
  const [correction, setCorrection] = useState('')
  const [feedbackComment, setFeedbackComment] = useState('')
  const [feedbackReason, setFeedbackReason] = useState('incorrect_information')
  const [selectionMode, setSelectionMode] = useState(false)
  const [selectedMessages, setSelectedMessages] = useState<Set<string>>(() => new Set())
  const conversationId = useRef<string>()
  const sessionLanguage = useRef('es')
  const noticeRef = useRef<HTMLParagraphElement>(null)
  const onlineRef = useRef(false)
  const statusCheckedRef = useRef(false)
  const activeTurnRef = useRef<string>()
  const activeSpeechQueueRef = useRef<PrefetchedSpeechQueue<Blob>>()
  const speechEpochRef = useRef(0)
  const processingAudioRef = useRef(false)
  const processingInterruptRef = useRef(false)
  const recentTranscriptRef = useRef<{ text: string; at: number }>()
  const busy = state === 'thinking' || state === 'speaking'
  const historyByDay = useMemo(() => {
    const groups = new Map<string, { label: string; items: HistoryItem[] }>()
    for (const item of history) {
      const date = new Date(item.created_at)
      const key = `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`
      const group = groups.get(key) ?? { label: historyDayLabel(date), items: [] }
      group.items.push(item)
      groups.set(key, group)
    }
    return [...groups.values()]
  }, [history])

  useEffect(() => {
    navigator.geolocation?.getCurrentPosition(
      ({ coords }) => setLocation({ latitude: coords.latitude, longitude: coords.longitude }),
      () => undefined,
      { enableHighAccuracy: false, maximumAge: 15 * 60 * 1000, timeout: 8000 }
    )
  }, [])

  const refreshHistory = useCallback(async () => {
    if (!coreOnline) return
    setHistoryLoading(true)
    try {
      const [items, persistedStats] = await Promise.all([getHistory(), getStats()])
      setHistory(items)
      setStats(persistedStats)
      const newestAssistant = items.find((item) => item.role === 'assistant')
      if (newestAssistant) setLatestResponse({ id: newestAssistant.id, rating: newestAssistant.rating })
    } catch { /* status already explains an unavailable core */ }
    finally { setHistoryLoading(false) }
  }, [coreOnline])

  useEffect(() => {
    if (coreOnline) void refreshHistory()
  }, [coreOnline, refreshHistory])

  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      try {
        const status = await getStatus()
        console.info('[JARVIS versions]', {
          web_build_sha: import.meta.env.VITE_BUILD_SHA || 'development',
          gateway_build_sha: status.gateway_build_sha,
          expected_web_build_sha: status.web_build_sha,
          core_build_sha: status.core?.build_sha || 'offline',
        })
        if (cancelled) return
        const firstCheck = !statusCheckedRef.current
        statusCheckedRef.current = true
        const wasOnline = onlineRef.current
        onlineRef.current = status.core_connected
        setCoreOnline(status.core_connected)
        if (!status.core_connected) {
          if (wasOnline) dispatch({ type: 'CORE_OFFLINE' })
          if (wasOnline || firstCheck) setNotice('El Core del PC está desconectado')
        } else if (!wasOnline) {
          if (muted) {
            dispatch({ type: 'MUTE' })
            setNotice('Pulsa la cara para volver a escuchar')
          } else {
            dispatch({ type: 'CORE_ONLINE' })
            setNotice(status.core?.ollama_ready === false ? 'Core conectado · Ollama no responde' : voiceReady ? 'Estoy escuchando' : 'Estoy escuchando · toca la boca para activar mi voz')
          }
        }
      } catch {
        if (!cancelled) {
          const firstCheck = !statusCheckedRef.current
          statusCheckedRef.current = true
          const wasOnline = onlineRef.current
          onlineRef.current = false
          setCoreOnline(false)
          if (wasOnline) dispatch({ type: 'CORE_OFFLINE' })
          if (wasOnline || firstCheck) setNotice('No puedo alcanzar el gateway')
        }
      }
    }
    void poll()
    const interval = window.setInterval(poll, 5000)
    return () => { cancelled = true; window.clearInterval(interval) }
  }, [muted, voiceReady])

  useEffect(() => {
    if (view === 'dashboard') void refreshHistory()
  }, [view, refreshHistory])

  useEffect(() => {
    if (noticeRef.current) noticeRef.current.scrollTop = noticeRef.current.scrollHeight
  }, [notice])

  const cancelActiveSpeech = useCallback(() => {
    speechEpochRef.current += 1
    activeSpeechQueueRef.current?.cancel()
    activeSpeechQueueRef.current = undefined
    activeTurnRef.current = undefined
    cancelSpeechPlayback()
    setAudioPlaying(false)
  }, [])

  const runConversation = useCallback(async (
    message: string, language?: string, languageConfidence?: number, requestedTurnId?: string,
  ) => {
    const cleanMessage = message.trim()
    if (!cleanMessage || !coreOnline) return
    if (activeTurnRef.current) return
    const turnId = requestedTurnId || crypto.randomUUID()
    const speechEpoch = speechEpochRef.current + 1
    speechEpochRef.current = speechEpoch
    activeTurnRef.current = turnId
    dispatch({ type: 'SUBMIT' })
    setNotice(cleanMessage)
    let turnSpeechQueue: PrefetchedSpeechQueue<Blob> | undefined
    try {
      const shouldSpeak = soundEnabled && voiceReady && !muted
      let fullText = ''
      let speechBuffer = ''
      let responseStarted = false
      let speechFailed = false
      const speechLanguage = sessionLanguage.current
      const speechQueue = new PrefetchedSpeechQueue<Blob>({
        synthesize: (text) => synthesizeSpeech(text, speechLanguage, turnId),
        play: (speech) => playAudio(speech, setAudioPlaying),
        onError: () => { speechFailed = true },
      })
      turnSpeechQueue = speechQueue
      activeSpeechQueueRef.current = speechQueue

      const queueSpeech = (flush = false) => {
        if (!shouldSpeak) return
        const split = takeSpeechSegments(speechBuffer, flush)
        speechBuffer = split.remainder
        for (const segment of split.segments) speechQueue.enqueue(segment)
      }

      const response = await streamMessage(cleanMessage, conversationId.current, location, language, languageConfidence, turnId, (chunk) => {
        if (speechEpoch !== speechEpochRef.current) return
        fullText += chunk
        setNotice(cleanAssistantText(fullText))
        if (!responseStarted) {
          responseStarted = true
          dispatch({ type: 'RESPONSE' })
        }
        if (shouldSpeak) {
          speechBuffer += chunk
          queueSpeech()
        }
      })
      if (speechEpoch !== speechEpochRef.current) return
      conversationId.current = response.conversation_id
      sessionLanguage.current = response.language || sessionLanguage.current
      setLatestResponse({ id: response.message_id, rating: null })
      fullText = cleanAssistantText(response.message || fullText)
      setNotice(fullText)
      if (!responseStarted) dispatch({ type: 'RESPONSE' })
      void refreshHistory()
      if (shouldSpeak) {
        queueSpeech(true)
        await speechQueue.drain()
        if (speechEpoch !== speechEpochRef.current) return
        if (speechFailed) {
          setVoiceReady(false)
          setNotice(`${fullText}\nToca la boca para volver a activar la voz.`)
        }
      } else if (soundEnabled && !voiceReady) {
        setNotice(`${fullText}\nToca la boca para activar la voz.`)
      }
      dispatch({ type: 'SPEECH_END' })
    } catch (error) {
      if (speechEpoch !== speechEpochRef.current) return
      setAudioPlaying(false)
      setNotice(error instanceof Error ? error.message : 'No he podido completar la solicitud')
      dispatch({ type: 'FAIL' })
    } finally {
      if (activeSpeechQueueRef.current === turnSpeechQueue) activeSpeechQueueRef.current = undefined
      if (activeTurnRef.current === turnId) activeTurnRef.current = undefined
    }
  }, [coreOnline, location, muted, refreshHistory, soundEnabled, voiceReady])

  const toggleSound = () => {
    if (!voiceReady) {
      void unlockSpeech().then((ready) => {
        setVoiceReady(ready)
        if (ready) {
          setSoundEnabled(true)
          localStorage.setItem('jarvis-sound', 'true')
          setNotice('Voz activada. Estoy escuchando.')
        } else {
          setNotice('Safari no ha permitido el audio. Vuelve a tocar la boca.')
        }
      })
      return
    }
    const next = !soundEnabled
    setSoundEnabled(next)
    localStorage.setItem('jarvis-sound', String(next))
    setNotice(next ? 'Voz activada. Estoy escuchando.' : 'Voz silenciada. Seguiré respondiendo por texto.')
  }

  const processAudio = useCallback(async (
    audio: Blob, metadata: AudioCaptureMetadata, lifecycle: VoiceUtteranceLifecycle,
  ) => {
    if (processingAudioRef.current) return
    processingAudioRef.current = true
    const utteranceId = metadata.utteranceId
    dispatch({ type: 'SUBMIT' })
    setNotice('Transcribiendo…')
    try {
      const transcription = await transcribeAudio(audio, metadata, utteranceId, conversationId.current)
      console.info('[JARVIS voice]', {
        utterance_id: utteranceId,
        event: 'transcript',
        transcript: transcription.transcript,
        discard_reason: transcription.discardReason ?? 'none',
      })
      lifecycle.processing()
      if (!transcription.transcript) {
        setNotice('Estoy escuchando')
        dispatch({ type: 'EMPTY_AUDIO' })
        return
      }
      const normalized = transcription.transcript.toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim()
      const previous = recentTranscriptRef.current
      if (previous && previous.text === normalized && Date.now() - previous.at < 8_000) {
        setNotice('Estoy escuchando')
        dispatch({ type: 'EMPTY_AUDIO' })
        return
      }
      recentTranscriptRef.current = { text: normalized, at: Date.now() }
      void runConversation(
        transcription.transcript, transcription.language, transcription.languageConfidence,
        crypto.randomUUID(),
      )
    } catch (error) {
      console.warn('No se pudo transcribir la grabación', error)
      setNotice('No he podido entenderte. Sigo escuchando.')
      dispatch({ type: 'EMPTY_AUDIO' })
    } finally {
      processingAudioRef.current = false
    }
  }, [runConversation])

  const processInterruptAudio = useCallback(async (
    audio: Blob, metadata: AudioCaptureMetadata,
  ) => {
    if (processingInterruptRef.current) return
    processingInterruptRef.current = true
    try {
      const transcription = await transcribeAudio(
        audio, metadata, metadata.utteranceId, conversationId.current,
      )
      const interruption = parseSpeechInterrupt(transcription.transcript)
      console.info('[JARVIS voice]', {
        utterance_id: metadata.utteranceId,
        event: 'interrupt_transcript',
        transcript: transcription.transcript,
        interrupt_action: interruption.kind,
      })
      if (interruption.kind === 'ignore') return
      cancelActiveSpeech()
      dispatch({ type: 'SPEECH_END' })
      setNotice('Estoy escuchando')
      if (interruption.kind === 'message') {
        void runConversation(
          interruption.message, transcription.language, transcription.languageConfidence,
          crypto.randomUUID(),
        )
      }
    } catch (error) {
      console.warn('No se pudo comprobar la interrupción', error)
    } finally {
      processingInterruptRef.current = false
    }
  }, [cancelActiveSpeech, runConversation])

  const voiceCapture = useContinuousVoice({
    enabled: coreOnline && !muted && view === 'face' && state !== 'error',
    paused: busy,
    conversationState: state,
    onListening: useCallback(() => dispatch({ type: 'START_LISTENING' }), []),
    onUtterance: useCallback((audio, metadata, lifecycle) => processAudio(audio, metadata, lifecycle), [processAudio]),
    onInterruptUtterance: useCallback((audio, metadata) => processInterruptAudio(audio, metadata), [processInterruptAudio]),
    onError: useCallback((message) => { setNotice(message); dispatch({ type: 'FAIL' }) }, [])
  })

  const toggleMute = () => {
    if (!coreOnline) return
    if (state === 'error' && !muted) {
      dispatch({ type: 'RESET' })
      setNotice('Estoy escuchando')
      return
    }
    const nextMuted = !muted
    setMuted(nextMuted)
    localStorage.setItem('jarvis-muted', String(nextMuted))
    dispatch({ type: nextMuted ? 'MUTE' : 'UNMUTE' })
    setNotice(nextMuted ? 'Pulsa la cara para volver a escuchar' : 'Estoy escuchando')
  }

  const submitManual = (event: FormEvent) => {
    event.preventDefault()
    const message = input.trim()
    if (!message) return
    setInput('')
    void runConversation(message)
  }

  const rate = async (messageId: string, rating: 'good' | 'bad') => {
    if (rating === 'bad') {
      setBadMessage(messageId)
      setCorrection('')
      setFeedbackComment('')
      setFeedbackReason('incorrect_information')
      return
    }
    await sendFeedback(messageId, rating)
    setLatestResponse((current) => current?.id === messageId ? { ...current, rating } : current)
    await refreshHistory()
  }

  const submitCorrection = async (event: FormEvent) => {
    event.preventDefault()
    if (!badMessage) return
    await sendFeedback(badMessage, 'bad', {
      reasonCode: feedbackReason,
      comment: feedbackComment.trim() || undefined,
      expectedBehavior: correction.trim() || undefined,
    })
    setLatestResponse((current) => current?.id === badMessage ? { ...current, rating: 'bad' } : current)
    setBadMessage(null)
    setCorrection('')
    setFeedbackComment('')
    await refreshHistory()
  }

  const toggleHistorySelection = (messageId: string) => {
    setSelectedMessages((current) => {
      const next = new Set(current)
      if (next.has(messageId)) next.delete(messageId)
      else next.add(messageId)
      return next
    })
  }

  const copyHistory = async (items: HistoryItem[]) => {
    if (!items.length) return
    try {
      await copyPlainText(formatHistorySelection(items))
      setNotice(`${items.length} mensajes copiados`)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'No se pudo copiar la conversación')
    }
  }

  const closeSelection = () => {
    setSelectionMode(false)
    setSelectedMessages(new Set())
  }

  const correctionDialog = badMessage && (
    <div className="dialog-backdrop" onMouseDown={() => setBadMessage(null)}>
      <form className="correction-dialog" onSubmit={submitCorrection} onMouseDown={(event) => event.stopPropagation()}>
        <button type="button" className="dialog-close" onClick={() => setBadMessage(null)}><X size={18} /></button>
        <h2>¿Por qué estuvo mal?</h2>
        <p>Se guardará la causa, el contexto y las tools del turno como dato de entrenamiento.</p>
        <select value={feedbackReason} onChange={(event) => setFeedbackReason(event.target.value)} aria-label="Motivo del feedback">
          <option value="incorrect_information">Información incorrecta</option>
          <option value="should_have_used_tool">Debería haber consultado una tool</option>
          <option value="wrong_tool">Utilizó la tool equivocada</option>
          <option value="action_not_executed">No ejecutó la acción solicitada</option>
          <option value="ignored_context">Ignoró el contexto</option>
          <option value="repeated_response">Repitió una respuesta anterior</option>
          <option value="too_long">Demasiado largo</option>
          <option value="too_short">Demasiado corto</option>
          <option value="wrong_tone">Tono incorrecto</option>
          <option value="other">Otro</option>
        </select>
        <textarea autoFocus value={feedbackComment} onChange={(event) => setFeedbackComment(event.target.value)} rows={3} placeholder="Comentario opcional" />
        <textarea value={correction} onChange={(event) => setCorrection(event.target.value)} rows={4} placeholder="¿Qué debería haber hecho? (opcional)" />
        <button className="save-button">Guardar feedback</button>
      </form>
    </div>
  )

  if (view === 'dashboard') {
    return (
      <>
      <main className="dashboard">
        <header className="dashboard-header">
          <button className="plain-button" onClick={() => { closeSelection(); setView('face') }}><ArrowLeft size={18} /> Volver</button>
          <div><h1>Conversaciones</h1><p>{coreOnline ? 'Core conectado' : 'Core desconectado'}</p></div>
          <button className="plain-button history-select-button" onClick={() => selectionMode ? closeSelection() : setSelectionMode(true)}>{selectionMode ? 'Cancelar' : 'Seleccionar'}</button>
        </header>

        {selectionMode && (
          <section className="history-selection" aria-label="Acciones de selección">
            <span>{selectedMessages.size} seleccionados</span>
            <button disabled={!selectedMessages.size} onClick={() => void copyHistory(history.filter((item) => selectedMessages.has(item.id)))}><Copy size={15} /> Copiar</button>
            <button onClick={() => void copyHistory(history.filter((item) => sameLocalDay(new Date(item.created_at), new Date())))}><Copy size={15} /> Copiar conversación completa de hoy</button>
          </section>
        )}

        <section className="history-stats" aria-label="Estadísticas persistentes">
          <span><strong>{stats.messages}</strong> Mensajes</span>
          <span className="stat-positive"><strong>{stats.positives}</strong> Positivos</span>
          <span className="stat-negative"><strong>{stats.negatives}</strong> Negativos</span>
        </section>

        <section className="history" aria-live="polite">
          {historyLoading && <p className="empty">Cargando…</p>}
          {!historyLoading && history.length === 0 && <p className="empty">Todavía no hay conversaciones guardadas.</p>}
          {historyByDay.map((group, groupIndex) => (
            <details className="history-day" key={group.label} open={groupIndex === 0}>
              <summary><span>{group.label}</span><small>{group.items.length} mensajes</small></summary>
              <div className="history-day-items">
                {group.items.map((item) => (
                  <article
                    key={item.id}
                    className={`history-item history-item--${item.role} ${selectedMessages.has(item.id) ? 'history-item--selected' : ''}`}
                    onClick={() => selectionMode && toggleHistorySelection(item.id)}
                    role={selectionMode ? 'checkbox' : undefined}
                    aria-checked={selectionMode ? selectedMessages.has(item.id) : undefined}
                    tabIndex={selectionMode ? 0 : undefined}
                    onKeyDown={(event) => {
                      if (selectionMode && (event.key === 'Enter' || event.key === ' ')) {
                        event.preventDefault(); toggleHistorySelection(item.id)
                      }
                    }}
                  >
                    <small>{item.role === 'user' ? 'Tú' : 'JARVIS'} · {new Date(item.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</small>
                    <p>{item.role === 'assistant' ? cleanAssistantText(item.content) : item.content}</p>
                    {item.role === 'assistant' && (
                      <div className="feedback">
                        <button className={item.rating === 'good' ? 'selected' : ''} onClick={(event) => { event.stopPropagation(); void rate(item.id, 'good') }} aria-label="Recompensa positiva, más uno"><Cookie size={15} /></button>
                        <button className={item.rating === 'bad' ? 'selected' : ''} onClick={(event) => { event.stopPropagation(); void rate(item.id, 'bad') }} aria-label="Recompensa negativa, menos uno"><WhipIcon /></button>
                        {item.correction && <span><Check size={13} /> Corrección guardada</span>}
                      </div>
                    )}
                  </article>
                ))}
              </div>
            </details>
          ))}
        </section>

        <form className="manual-composer" onSubmit={submitManual}>
          <input value={input} onChange={(event) => setInput(event.target.value)} placeholder="Escribe a JARVIS…" disabled={!coreOnline || busy} />
          <button disabled={!input.trim() || !coreOnline || busy} aria-label="Enviar"><Send size={18} /></button>
        </form>

      </main>
      {correctionDialog}
      </>
    )
  }

  return (
    <>
    <main className="app">
      <div className="quick-feedback" aria-label="Valorar la última respuesta de JARVIS">
        <button disabled={!latestResponse} className={latestResponse?.rating === 'good' ? 'selected' : ''} onClick={() => latestResponse && void rate(latestResponse.id, 'good')} aria-label="Marcar última respuesta como buena" aria-pressed={latestResponse?.rating === 'good'}><Cookie size={18} /></button>
        <button disabled={!latestResponse} className={latestResponse?.rating === 'bad' ? 'selected' : ''} onClick={() => latestResponse && void rate(latestResponse.id, 'bad')} aria-label="Marcar última respuesta como mala" aria-pressed={latestResponse?.rating === 'bad'}><WhipIcon size={18} /></button>
        <button
          disabled={!voiceCapture.canFinalize}
          onClick={() => {
            if (voiceCapture.finalizeNow()) setNotice('Finalizando audio…')
          }}
          aria-label="Finalizar y enviar la grabación ahora"
          title="Enviar audio ahora"
        ><Send size={18} /></button>
      </div>
      <button className="menu-button" onClick={() => setMenuOpen(!menuOpen)} aria-label="Abrir menú"><Menu size={24} /></button>
      {menuOpen && (
        <nav className="menu">
          <button onClick={() => { setView('dashboard'); setMenuOpen(false) }}><History size={18} /> Historial</button>
          <button onClick={toggleSound}>
            {soundEnabled && voiceReady ? <Volume2 size={18} /> : <VolumeX size={18} />} {voiceReady ? `Voz ${soundEnabled ? 'activada' : 'desactivada'}` : 'Activar voz'}
          </button>
          <a className="menu-attribution" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">Ubicación © OpenStreetMap</a>
        </nav>
      )}

      <section className="presence">
        <JarvisFace state={state} playing={audioPlaying} voiceEnabled={soundEnabled && voiceReady} onClick={toggleMute} onToggleVoice={toggleSound} />
        <p className="state-label">{stateLabels[state]}</p>
        <p className="notice" ref={noticeRef}>{notice}</p>
      </section>
    </main>
    {correctionDialog}
    </>
  )
}
