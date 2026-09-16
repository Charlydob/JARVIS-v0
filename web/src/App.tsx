import { FormEvent, useCallback, useEffect, useReducer, useRef, useState } from 'react'
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
import { JarvisFace } from './components/JarvisFace'
import { useContinuousVoice } from './hooks/useContinuousVoice'
import { JarvisState, stateLabels, transition } from './state/machine'

type View = 'face' | 'dashboard'

function playAudio(blob: Blob): Promise<void> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob)
    const audio = new Audio(url)
    audio.onended = () => { URL.revokeObjectURL(url); resolve() }
    audio.onerror = () => { URL.revokeObjectURL(url); reject(new Error('No se pudo reproducir la voz')) }
    audio.play().catch((error) => { URL.revokeObjectURL(url); reject(error) })
  })
}

export default function App() {
  const [state, dispatch] = useReducer(transition, 'sleeping' as JarvisState)
  const [view, setView] = useState<View>('face')
  const [menuOpen, setMenuOpen] = useState(false)
  const [muted, setMuted] = useState(() => localStorage.getItem('jarvis-muted') === 'true')
  const [soundEnabled, setSoundEnabled] = useState(() => localStorage.getItem('jarvis-sound') !== 'false')
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
            setNotice(status.core?.ollama_ready === false ? 'Core conectado · Ollama no responde' : 'Estoy escuchando')
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
  }, [muted])

  useEffect(() => {
    if (view === 'dashboard') void refreshHistory()
  }, [view, refreshHistory])

  const runConversation = useCallback(async (message: string) => {
    const cleanMessage = message.trim()
    if (!cleanMessage || !coreOnline) return
    dispatch({ type: 'SUBMIT' })
    setNotice(cleanMessage)
    try {
      const response = await sendMessage(cleanMessage, conversationId.current)
      conversationId.current = response.conversation_id
      setNotice(response.message)
      dispatch({ type: 'RESPONSE' })
      void refreshHistory()
      if (soundEnabled && !muted) {
        try {
          const speech = await synthesizeSpeech(response.message)
          await playAudio(speech)
        } catch {
          setNotice(`${response.message}\nLa respuesta de voz no se pudo reproducir.`)
        }
      }
      dispatch({ type: 'SPEECH_END' })
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'No he podido completar la solicitud')
      dispatch({ type: 'FAIL' })
    }
  }, [coreOnline, muted, refreshHistory, soundEnabled])

  const processAudio = useCallback(async (audio: Blob) => {
    dispatch({ type: 'SUBMIT' })
    setNotice('Transcribiendo…')
    try {
      const transcript = await transcribeAudio(audio)
      if (!transcript) {
        setNotice('Estoy escuchando')
        dispatch({ type: 'EMPTY_AUDIO' })
        return
      }
      await runConversation(transcript)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'No he podido entender el audio')
      dispatch({ type: 'FAIL' })
    }
  }, [runConversation])

  useContinuousVoice({
    enabled: coreOnline && !muted && !busy && view === 'face' && state !== 'error',
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
          {history.map((item) => (
            <article key={item.id} className={`history-item history-item--${item.role}`}>
              <small>{item.role === 'user' ? 'Tú' : 'JARVIS'} · {new Date(item.created_at).toLocaleString()}</small>
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
          <button onClick={() => { const next = !soundEnabled; setSoundEnabled(next); localStorage.setItem('jarvis-sound', String(next)) }}>
            {soundEnabled ? <Volume2 size={18} /> : <VolumeX size={18} />} Voz {soundEnabled ? 'activada' : 'desactivada'}
          </button>
        </nav>
      )}

      <section className="presence">
        <JarvisFace state={state} onClick={toggleMute} />
        <p className="state-label">{stateLabels[state]}</p>
        <p className="notice">{notice}</p>
      </section>
    </main>
  )
}
