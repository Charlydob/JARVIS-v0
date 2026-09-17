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
    >
      {/* =========================
          IDLE
      ========================= */}

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

      {/* =========================
          THINKING REFERENCES
      ========================= */}

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

      {/* =========================
          LISTENING REFERENCES
      ========================= */}

      <g
        id="listening-reference"
        style={{ display: 'none' }}
      >
        <ellipse
          id="listening-eye-left"
          cx="350"
          cy="360"
          rx="54"
          ry="69"
          fill="#DFF6FF"
        />

        <ellipse
          id="listening-eye-right"
          cx="650"
          cy="360"
          rx="54"
          ry="69"
          fill="#DFF6FF"
        />

        <rect
          id="listening-mouth"
          x="445"
          y="529"
          width="110"
          height="18"
          rx="9"
          ry="9"
          fill="#FFFFFF"
        />

        <circle
          id="listening-color-peak"
          cx="0"
          cy="0"
          r="1"
          fill="#7FDBFF"
        />
      </g>

      {/* =========================
          SPEAKING REFERENCES
      ========================= */}

      <g
        id="speaking-reference"
        style={{ display: 'none' }}
      >
        <rect
          id="speaking-mouth-closed"
          x="415"
          y="527"
          width="170"
          height="26"
          rx="13"
          ry="13"
          fill="#FFFFFF"
        />

        <rect
          id="speaking-mouth-medium"
          x="437.5"
          y="511"
          width="125"
          height="58"
          rx="29"
          ry="29"
          fill="#FFFFFF"
        />

        <rect
          id="speaking-mouth-open"
          x="455"
          y="497"
          width="90"
          height="86"
          rx="43"
          ry="43"
          fill="#FFFFFF"
        />
      </g>

      {/* =========================
          SLEEPING REFERENCES
      ========================= */}

      <g
        id="sleeping-reference"
        style={{ display: 'none' }}
      >
        <rect
          id="sleeping-eye-left"
          x="290"
          y="352"
          width="120"
          height="18"
          rx="9"
          ry="9"
          fill="#FFFFFF"
        />

        <rect
          id="sleeping-eye-right"
          x="590"
          y="352"
          width="120"
          height="18"
          rx="9"
          ry="9"
          fill="#FFFFFF"
        />

        <rect
          id="sleeping-mouth"
          x="445"
          y="532"
          width="110"
          height="16"
          rx="8"
          ry="8"
          fill="#FFFFFF"
        />
      </g>

      {/* ZZZ reales del estado sleeping */}

      <g
        id="sleeping-zzz"
        style={{
          opacity: 0,
          pointerEvents: 'none'
        }}
      >
        <text
          id="zzz-1"
          x="742"
          y="248"
          fill="#FFFFFF"
          fontSize="26"
          fontFamily="Arial, sans-serif"
          fontWeight="700"
        >
          z
        </text>

        <text
          id="zzz-2"
          x="785"
          y="206"
          fill="#FFFFFF"
          fontSize="40"
          fontFamily="Arial, sans-serif"
          fontWeight="700"
        >
          Z
        </text>

        <text
          id="zzz-3"
          x="838"
          y="150"
          fill="#FFFFFF"
          fontSize="58"
          fontFamily="Arial, sans-serif"
          fontWeight="700"
        >
          Z
        </text>
      </g>

      {/* =========================
          ERROR
          
          IMPORTANTE:
          El grupo NO puede usar display:none.
          Los paths empiezan con opacity:0
          y error.ts los activa.
      ========================= */}

      <g
        id="error-reference"
        style={{
          pointerEvents: 'none'
        }}
      >
        <path
          id="error-eye-left"
          d="M 305 315 L 395 405 M 395 315 L 305 405"
          fill="none"
          stroke="#FF3B3B"
          strokeWidth="24"
          strokeLinecap="round"
          style={{ opacity: 0 }}
        />

        <path
          id="error-eye-right"
          d="M 605 315 L 695 405 M 695 315 L 605 405"
          fill="none"
          stroke="#FF3B3B"
          strokeWidth="24"
          strokeLinecap="round"
          style={{ opacity: 0 }}
        />

        <path
          id="error-mouth"
          d="
            M 420 548
            L 450 518
            L 480 548
            L 510 518
            L 540 548
            L 570 518
          "
          fill="none"
          stroke="#FF3B3B"
          strokeWidth="18"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ opacity: 0 }}
        />
      </g>

      {/* =========================
          CONTROL INVISIBLE BOCA
      ========================= */}

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
          if (
            event.key === 'Enter' ||
            event.key === ' '
          ) {
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