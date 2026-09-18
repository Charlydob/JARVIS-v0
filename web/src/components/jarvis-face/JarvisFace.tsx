import {
  useEffect,
  useRef
} from 'react'

import type { JarvisState } from '../../state/machine'

import { FaceSvg } from './FaceSvg'
import './jarvis-face.css'

import type { FaceElements } from './animations/types'

import { startIdleAnimation } from './animations/idle'
import { startListeningAnimation } from './animations/listening'
import {
  runThinkingAnimation
} from './animations/thinking'
import { startSpeakingAnimation } from './animations/speaking'
import { startSleepingAnimation } from './animations/sleeping'
import { startErrorAnimation } from './animations/error'
import { resetFaceToCanonicalState } from './animations/canonical'

type Props = {
  state: JarvisState
  playing: boolean
  voiceEnabled: boolean
  onClick: () => void
  onToggleVoice: () => void
}

export function JarvisFace({
  state,
  playing,
  voiceEnabled,
  onClick,
  onToggleVoice
}: Props) {
  const svgRef =
    useRef<SVGSVGElement | null>(null)

  const leftEyeRef =
    useRef<SVGCircleElement | null>(null)

  const rightEyeRef =
    useRef<SVGCircleElement | null>(null)

  const mouthRef =
    useRef<SVGRectElement | null>(null)

  const stopAnimationRef = useRef<(() => void) | null>(null)

  /*
    Ejecutar la animación correspondiente
    al estado visual actual.
  */
  useEffect(() => {
    if (
      !svgRef.current ||
      !leftEyeRef.current ||
      !rightEyeRef.current ||
      !mouthRef.current
    ) {
      return
    }

    const elements: FaceElements = {
      svg: svgRef.current,
      leftEye: leftEyeRef.current,
      rightEye: rightEyeRef.current,
      mouth: mouthRef.current
    }

    stopAnimationRef.current?.()
    resetFaceToCanonicalState(elements, state)

    let stopped = false
    let stop: () => void

    if (state === 'thinking') {
      const controller =
        new AbortController()
      void runThinkingAnimation(
        elements,
        controller.signal
      )
      stop = () => controller.abort()
    } else if (state === 'listening') {
      stop = startListeningAnimation(elements)
    } else if (state === 'speaking') {
      stop = startSpeakingAnimation(
        elements,
        playing
      )
    } else if (state === 'sleeping' || state === 'muted') {
      stop = startSleepingAnimation(elements)
    } else if (state === 'error') {
      stop = startErrorAnimation(elements)
    } else {
      stop = startIdleAnimation(elements)
    }

    const stopCurrent = () => {
      if (stopped) return
      stopped = true
      stop()
      resetFaceToCanonicalState(elements, state)
    }
    stopAnimationRef.current = stopCurrent
    return () => {
      stopCurrent()
      if (stopAnimationRef.current === stopCurrent) stopAnimationRef.current = null
    }
  }, [state, playing])

  return (
    <div
      className={[
        'jarvis-face',
        `jarvis-face--${state}`,
        voiceEnabled
          ? ''
          : 'jarvis-face--voice-muted'
      ]
        .filter(Boolean)
        .join(' ')}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(event) => {
        if (
          event.key === 'Enter' ||
          event.key === ' '
        ) {
          onClick()
        }
      }}
      aria-label={
        state === 'muted'
          ? 'Activar escucha'
          : 'Silenciar micrófono'
      }
    >
      <FaceSvg
        svgRef={svgRef}
        leftEyeRef={leftEyeRef}
        rightEyeRef={rightEyeRef}
        mouthRef={mouthRef}
        voiceEnabled={voiceEnabled}
        onToggleVoice={onToggleVoice}
      />
    </div>
  )
}
