import { FormEvent, useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { ArrowLeft, Check, History, Menu, Send, ThumbsDown, ThumbsUp, Volume2, VolumeX, X } from 'lucide-react'
import {
  getHistory,
  getStatus,
  HistoryItem,
  sendFeedback,
  sendMessage,
  synthesizeSpeech,
  transcribeAudio
} from './api/client'
import type { UserLocation } from './api/client'
import { JarvisFace } from './components/JarvisFace'
import { useContinuousVoice } from './hooks/useContinuousVoice'
import { JarvisState, stateLabels, transition } from './state/machine'

type View = 'face' | 'dashboard'

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

const speechAudio = new Audio()
speechAudio.preload = 'auto'
let speechUnlocked = false

function resetIOSAudioRoute() {
  const session = (navigator as Navigator & { audioSession?: { type: string } }).audioSession
  if (!session) return
  session.type = 'playback'
  session.type = 'auto'
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

function playAudio(blob: Blob): Promise<void> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob)
    resetIOSAudioRoute()
    speechAudio.pause()
    speechAudio.src = url
    speechAudio.volume = 1
    speechAudio.onended = () => { URL.revokeObjectURL(url); resolve() }
    speechAudio.onerror = () => { speechUnlocked = false; URL.revokeObjectURL(url); reject(new Error('No se pudo reproducir la voz')) }
    speechAudio.play().catch((error) => { speechUnlocked = false; URL.revokeObjectURL(url); reject(error) })
  })
}

export default function App() {
  const [state, dispatch] = useReducer(transition, 'sleeping' as JarvisState)
  const [view, setView] = useState<View>('face')
  const [menuOpen, setMenuOpen] = useState(false)
  const [muted, setMuted] = useState(() => localStorage.getItem('jarvis-muted') === 'true')
  const [soundEnabled, setSoundEnabled] = useState(() => localStorage.getItem('jarvis-sound') !== 'false')
  const [voiceReady, setVoiceReady] = useState(false)
  const [location, setLocation] = useState<UserLocation>()
  const [coreOnline, setCoreOnline] = useState(false)
  const [notice, setNotice] = useState('Conectando con el Core…')
  const [input, setInput] = useState('')
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [badMessage, setBadMessage] = useState<string | null>(null)
  const [correction, setCorrection] = useState('')
  const conversationId = useRef<string>()
  const onlineRef = useRef(false)
  const statusCheckedRef = useRef(false)
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
    try { setHistory(await getHistory()) } catch { /* status already explains an unavailable core */ }
    finally { setHistoryLoading(false) }
  }, [coreOnline])

  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      try {
        const status = await getStatus()
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

  const runConversation = useCallback(async (message: string, language?: string) => {
    const cleanMessage = message.trim()
    if (!cleanMessage || !coreOnline) return
    dispatch({ type: 'SUBMIT' })
    setNotice(cleanMessage)
    try {
      const response = await sendMessage(cleanMessage, conversationId.current, location, language)
      conversationId.current = response.conversation_id
      setNotice(response.message)
      dispatch({ type: 'RESPONSE' })
      void refreshHistory()
      if (soundEnabled && voiceReady && !muted) {
        try {
          const speech = await synthesizeSpeech(response.message, response.language || language)
          await playAudio(speech)
        } catch {
          setVoiceReady(false)
          setNotice(`${response.message}\nToca la boca para volver a activar la voz.`)
        }
      } else if (soundEnabled && !voiceReady) {
        setNotice(`${response.message}\nToca la boca para activar la voz.`)
      }
      dispatch({ type: 'SPEECH_END' })
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'No he podido completar la solicitud')
      dispatch({ type: 'FAIL' })
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

  const processAudio = useCallback(async (audio: Blob) => {
    dispatch({ type: 'SUBMIT' })
    setNotice('Transcribiendo…')
    try {
      const transcription = await transcribeAudio(audio)
      if (!transcription.transcript) {
        setNotice('Estoy escuchando')
        dispatch({ type: 'EMPTY_AUDIO' })
        return
      }
      await runConversation(transcription.transcript, transcription.language)
    } catch (error) {
      console.warn('No se pudo transcribir la grabación', error)
      setNotice('No he podido entenderte. Sigo escuchando.')
      dispatch({ type: 'EMPTY_AUDIO' })
    }
  }, [runConversation])

  useContinuousVoice({
    enabled: coreOnline && !muted && !busy && view === 'face' && state !== 'error',
    retainMicrophone: coreOnline && !muted && view === 'face' && state !== 'error',
    onListening: useCallback(() => dispatch({ type: 'START_LISTENING' }), []),
    onUtterance: useCallback((audio) => { void processAudio(audio) }, [processAudio]),
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
      return
    }
    await sendFeedback(messageId, rating)
    await refreshHistory()
  }

  const submitCorrection = async (event: FormEvent) => {
    event.preventDefault()
    if (!badMessage || !correction.trim()) return
    await sendFeedback(badMessage, 'bad', correction.trim())
    setBadMessage(null)
    setCorrection('')
    await refreshHistory()
  }

  if (view === 'dashboard') {
    return (
      <main className="dashboard">
        <header className="dashboard-header">
          <button className="plain-button" onClick={() => setView('face')}><ArrowLeft size={18} /> Volver</button>
          <div><h1>Conversaciones</h1><p>{coreOnline ? 'Core conectado' : 'Core desconectado'}</p></div>
        </header>

        <section className="history" aria-live="polite">
          {historyLoading && <p className="empty">Cargando…</p>}
          {!historyLoading && history.length === 0 && <p className="empty">Todavía no hay conversaciones guardadas.</p>}
          {historyByDay.map((group, groupIndex) => (
            <details className="history-day" key={group.label} open={groupIndex === 0}>
              <summary><span>{group.label}</span><small>{group.items.length} mensajes</small></summary>
              <div className="history-day-items">
                {group.items.map((item) => (
                  <article key={item.id} className={`history-item history-item--${item.role}`}>
                    <small>{item.role === 'user' ? 'Tú' : 'JARVIS'} · {new Date(item.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</small>
                    <p>{item.content}</p>
                    {item.role === 'assistant' && (
                      <div className="feedback">
                        <button className={item.rating === 'good' ? 'selected' : ''} onClick={() => void rate(item.id, 'good')} aria-label="Respuesta correcta"><ThumbsUp size={15} /></button>
                        <button className={item.rating === 'bad' ? 'selected' : ''} onClick={() => void rate(item.id, 'bad')} aria-label="Respuesta incorrecta"><ThumbsDown size={15} /></button>
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

        {badMessage && (
          <div className="dialog-backdrop" onMouseDown={() => setBadMessage(null)}>
            <form className="correction-dialog" onSubmit={submitCorrection} onMouseDown={(event) => event.stopPropagation()}>
              <button type="button" className="dialog-close" onClick={() => setBadMessage(null)}><X size={18} /></button>
              <h2>¿Qué debería haber respondido?</h2>
              <p>La corrección se guardará en el PC para futuros datos de entrenamiento.</p>
              <textarea autoFocus value={correction} onChange={(event) => setCorrection(event.target.value)} rows={5} />
              <button className="save-button" disabled={!correction.trim()}>Guardar corrección</button>
            </form>
          </div>
        )}
      </main>
    )
  }

  return (
    <main className="app">
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
        <JarvisFace state={state} voiceEnabled={soundEnabled && voiceReady} onClick={toggleMute} onToggleVoice={toggleSound} />
        <p className="state-label">{stateLabels[state]}</p>
        <p className="notice">{notice}</p>
      </section>
    </main>
  )
}
