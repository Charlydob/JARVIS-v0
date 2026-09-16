import type { JarvisState } from '../state/machine'

export function JarvisFace({ state }: { state: JarvisState }) {
  return (
    <div className={`face face--${state}`} aria-label={`JARVIS: ${state}`} role="img">
      <div className="aura" />
      <div className="eyes">
        <div className="eye"><span className="pupil" /></div>
        <div className="eye"><span className="pupil" /></div>
      </div>
      <div className="voice-bars" aria-hidden="true">
        {[0, 1, 2, 3, 4].map((bar) => <span key={bar} />)}
      </div>
    </div>
  )
}
