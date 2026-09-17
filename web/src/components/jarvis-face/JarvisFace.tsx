import {
  useEffect,
  useRef,
  useState
} from 'react'

import type { JarvisState } from '../../state/machine'

import { FaceSvg } from './FaceSvg'
import './jarvis-face.css'

import type { FaceElements } from './animations/types'

import { startIdleAnimation } from './animations/idle'
import { startListeningAnimation } from './animations/listening'
import {
  runThinkingAnimation,
  THINKING_EXIT_DURATION
} from './animations/thinking'
import { startSpeakingAnimation } from './animations/speaking'
import { startSleepingAnimation } from './animations/sleeping'
import { startErrorAnimation } from './animations/error'

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

  /*
    Estado visual independiente del estado lógico.

    Esto permite que THINKING pueda frenar y
    regresar a la cara antes de empezar SPEAKING.
  */
  const [visualState, setVisualState] =
    useState<JarvisState>(state)

  const pendingStateRef =
    useRef<JarvisState>(state)

  const thinkingAbortRef =
    useRef<AbortController | null>(null)

  const exitTimerRef =
    useRef<number | null>(null)

  /*
    Sincronizar estado lógico → estado visual.
  */
  useEffect(() => {
    pendingStateRef.current = state

    if (
      visualState === 'thinking' &&
      state !== 'thinking'
    ) {
      thinkingAbortRef.current?.abort()

      if (exitTimerRef.current === null) {
        exitTimerRef.current =
          window.setTimeout(() => {
            exitTimerRef.current = null

            setVisualState(
              pendingStateRef.current
            )
          }, THINKING_EXIT_DURATION)
      }

      return
    }

    if (visualState !== state) {
      setVisualState(state)
    }
  }, [state, visualState])

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

    if (visualState === 'thinking') {
      const controller =
        new AbortController()

      thinkingAbortRef.current =
        controller

      void runThinkingAnimation(
        elements,
        controller.signal
      )

      return () => {
        if (!controller.signal.aborted) {
          controller.abort()
        }
      }
    }

    if (visualState === 'listening') {
      return startListeningAnimation(elements)
    }

    if (visualState === 'speaking') {
      return startSpeakingAnimation(
        elements,
        playing
      )
    }

    if (visualState === 'sleeping') {
      return startSleepingAnimation(elements)
    }

    if (visualState === 'muted') {
      return startSleepingAnimation(elements)
    }

    if (visualState === 'error') {
      return startErrorAnimation(elements)
    }

    return startIdleAnimation(elements)
  }, [visualState, playing])

  /*
    Limpieza al desmontar.
  */
  useEffect(() => {
    return () => {
      thinkingAbortRef.current?.abort()

      if (exitTimerRef.current !== null) {
        window.clearTimeout(
          exitTimerRef.current
        )
      }
    }
  }, [])

  return (
    <div
      className={[
        'jarvis-face',
        `jarvis-face--${visualState}`,
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