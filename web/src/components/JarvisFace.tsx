import type { JarvisState } from '../state/machine'

export function JarvisFace({ state, onClick }: { state: JarvisState; onClick: () => void }) {
  return (
    <button className={`face face--${state}`} onClick={onClick} aria-label={state === 'muted' ? 'Activar escucha' : 'Silenciar JARVIS'}>
      <span className="eyebrows" aria-hidden="true"><i /><i /></span>
      <span className="eyes" aria-hidden="true">
        <i className="eye"><b /></i>
        <i className="eye"><b /></i>
      </span>
      <svg className="mouth" viewBox="0 0 160 58" aria-hidden="true">
        <path d="M 18 16 Q 80 62 142 16" />
      </svg>
    </button>
  )
}
