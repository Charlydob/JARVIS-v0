import type { JarvisState } from '../state/machine'

export function JarvisFace({ state, voiceEnabled, onClick, onToggleVoice }: { state: JarvisState; voiceEnabled: boolean; onClick: () => void; onToggleVoice: () => void }) {
  return (
    <div className={`face face--${state} ${voiceEnabled ? '' : 'face--voice-muted'}`} onClick={onClick} role="button" tabIndex={0} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') onClick() }} aria-label={state === 'muted' ? 'Activar escucha' : 'Silenciar micrófono'}>
      <span className="eyes" aria-hidden="true">
        <i className="eye" />
        <i className="eye" />
      </span>
      <button className="mouth-button" onClick={(event) => { event.stopPropagation(); onToggleVoice() }} aria-label={voiceEnabled ? 'Silenciar voz de JARVIS' : 'Activar voz de JARVIS'}>
        <svg className="mouth" viewBox="0 0 160 70" aria-hidden="true">
          <path className="smile" d="M 18 16 Q 80 62 142 16" />
          <g className="talking-mouth">
            <ellipse className="lip" cx="80" cy="36" rx="57" ry="25" />
            <ellipse className="mouth-cavity" cx="80" cy="36" rx="45" ry="15" />
          </g>
        </svg>
      </button>
    </div>
  )
}
