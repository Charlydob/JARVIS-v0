import { FormEvent, useEffect, useReducer, useRef, useState } from 'react'
import { Expand, Maximize2, Mic, Moon, Send, Settings, Square, X } from 'lucide-react'
import { sendMessage } from './api/client'
import { JarvisFace } from './components/JarvisFace'
import { JarvisState, stateLabels, transition } from './state/machine'

const greeting = 'Sistemas en línea. Estoy listo cuando tú lo estés.'

export default function App() {
  const [state, dispatch] = useReducer(transition, 'idle' as JarvisState)
  const [input, setInput] = useState('')
  const [transcript, setTranscript] = useState('')
  const [answer, setAnswer] = useState(greeting)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [soundEnabled, setSoundEnabled] = useState(true)
  const [compact, setCompact] = useState(false)
  const conversationId = useRef<string>()

  useEffect(() => {
    const handler = () => setCompact(Boolean(document.fullscreenElement))
    document.addEventListener('fullscreenchange', handler)
    return () => document.removeEventListener('fullscreenchange', handler)
  }, [])

  const toggleConversation = () => {
    if (state === 'sleeping') dispatch({ type: 'WAKE' })
    else if (state === 'listening') dispatch({ type: 'SLEEP' })
    else dispatch({ type: 'START_LISTENING' })
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const message = input.trim()
    if (!message) return
    setTranscript(message)
    setInput('')
    dispatch({ type: 'SUBMIT' })
    try {
      const response = await sendMessage(message, conversationId.current)
      conversationId.current = response.conversation_id
      setAnswer(response.message)
      dispatch({ type: 'RESPONSE' })
      window.setTimeout(() => dispatch({ type: 'SPEECH_END' }), soundEnabled ? 2200 : 500)
    } catch {
      setAnswer('No puedo conectar con el núcleo en este momento. Comprueba el servicio e inténtalo de nuevo.')
      dispatch({ type: 'FAIL' })
    }
  }

  const toggleFullscreen = async () => {
    if (document.fullscreenElement) await document.exitFullscreen()
    else await document.documentElement.requestFullscreen()
  }

  const active = state !== 'sleeping'
  return (
    <main className={compact ? 'app app--display' : 'app'}>
      <header className="topbar">
        <div className="brand"><span className="brand-mark" />JARVIS <small>PERSONAL CORE</small></div>
        <div className="top-actions">
          <button className="icon-button" onClick={toggleFullscreen} aria-label="Pantalla completa"><Maximize2 size={18} /></button>
          <button className="icon-button" onClick={() => setSettingsOpen(true)} aria-label="Configuración"><Settings size={18} /></button>
        </div>
      </header>

      <section className="presence">
        <div className="status"><span className={`status-dot status-dot--${state}`} />{stateLabels[state]}</div>
        <JarvisFace state={state} />
        <p className="hint">{state === 'listening' ? 'Te escucho…' : state === 'thinking' ? 'Procesando solicitud…' : '¿En qué puedo ayudarte?'}</p>
      </section>

      {!compact && <section className="conversation" aria-live="polite">
        <article className="message message--user">
          <span>TÚ</span><p>{transcript || 'Aún no has dicho nada.'}</p>
        </article>
        <article className="message message--jarvis">
          <span>JARVIS</span><p>{answer}</p>
        </article>
      </section>}

      <section className="controls">
        {!compact && <form onSubmit={submit} className="composer">
          <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Escribe un mensaje…" aria-label="Mensaje" disabled={state === 'thinking'} />
          <button type="submit" aria-label="Enviar" disabled={!input.trim() || state === 'thinking'}><Send size={18} /></button>
        </form>}
        <button className={`talk-button ${state === 'listening' ? 'talk-button--active' : ''}`} onClick={toggleConversation}>
          {state === 'listening' ? <Square size={18} fill="currentColor" /> : active ? <Mic size={21} /> : <Moon size={20} />}
          <span>{state === 'listening' ? 'Detener' : active ? 'Iniciar conversación' : 'Activar JARVIS'}</span>
        </button>
      </section>

      {settingsOpen && <div className="modal-backdrop" onMouseDown={() => setSettingsOpen(false)}>
        <aside className="settings" onMouseDown={(e) => e.stopPropagation()} aria-label="Configuración">
          <div className="settings-title"><div><small>SISTEMA</small><h2>Configuración</h2></div><button className="icon-button" onClick={() => setSettingsOpen(false)}><X size={20} /></button></div>
          <label className="setting-row"><span><b>Respuesta por voz</b><small>Reproducir las respuestas de JARVIS</small></span><input type="checkbox" checked={soundEnabled} onChange={(e) => setSoundEnabled(e.target.checked)} /></label>
          <button className="setting-row setting-button" onClick={toggleFullscreen}><span><b>Modo display</b><small>Interfaz limpia a pantalla completa</small></span><Expand size={19} /></button>
          <button className="sleep-button" onClick={() => { dispatch({ type: 'SLEEP' }); setSettingsOpen(false) }}><Moon size={17} /> Poner en reposo</button>
        </aside>
      </div>}
    </main>
  )
}
