import type { Ref } from 'react'

type Props = {
  svgRef: Ref<SVGSVGElement>
  leftEyeRef: Ref<SVGCircleElement>
  rightEyeRef: Ref<SVGCircleElement>
  mouthRef: Ref<SVGRectElement>
  voiceEnabled: boolean
  onToggleVoice: () => void
}

export function FaceSvg({
  svgRef,
  leftEyeRef,
  rightEyeRef,
  mouthRef,
  voiceEnabled,
  onToggleVoice
}: Props) {
  return (
    <svg
      ref={svgRef}
      className="jarvis-face-svg"
      viewBox="0 0 1000 1000"
      preserveAspectRatio="xMidYMid meet"
      aria-hidden="true"
    >
      <g id="idle">
        <circle
          ref={leftEyeRef}
          id="eye-left"
          className="jarvis-eye"
          cx="350"
          cy="360"
          r="60"
          fill="currentColor"
        />

        <circle
          ref={rightEyeRef}
          id="eye-right"
          className="jarvis-eye"
          cx="650"
          cy="360"
          r="60"
          fill="currentColor"
        />

        <rect
          ref={mouthRef}
          id="mouth"
          className="jarvis-mouth"
          x="410"
          y="520"
          width="180"
          height="40"
          rx="18.897638"
          ry="18.897638"
          fill="currentColor"
        />
      </g>

      {/* Solo referencias geométricas para THINKING */}
      <g
        id="thinking-reference"
        style={{ display: 'none' }}
      >
        <circle
          id="thinking-orbit-guide"
          cx="500"
          cy="430"
          r="95"
        />

        <circle
          id="thinking-dot-1"
          cx="500"
          cy="335"
          r="30"
        />

        <circle
          id="thinking-dot-2"
          cx="582.272"
          cy="477.5"
          r="30"
        />

        <circle
          id="thinking-dot-3"
          cx="417.728"
          cy="477.5"
          r="30"
        />
      </g>

      {/* Zona grande invisible para poder pulsar la boca cómodamente */}
      <g
        className="jarvis-mouth-control"
        role="button"
        tabIndex={0}
        aria-label={
          voiceEnabled
            ? 'Silenciar voz de JARVIS'
            : 'Activar voz de JARVIS'
        }
        onClick={(event) => {
          event.stopPropagation()
          onToggleVoice()
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            event.stopPropagation()
            onToggleVoice()
          }
        }}
      >
        <rect
          x="370"
          y="480"
          width="260"
          height="120"
          fill="transparent"
          pointerEvents="all"
        />
      </g>
    </svg>
  )
}