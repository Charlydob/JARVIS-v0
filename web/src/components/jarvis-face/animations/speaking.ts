import type { FaceElements, StopAnimation } from './types'
import { prefersReducedMotion } from './types'

export function startSpeakingAnimation(
  { leftEye, rightEye, mouth }: FaceElements,
  playing: boolean
): StopAnimation {
  if (prefersReducedMotion()) return () => {}

  const left = leftEye.animate(
    [
      { transform: 'scale(1)' },
      { transform: 'scale(.98, 1.02)' },
      { transform: 'scale(1)' }
    ],
    {
      duration: 2300,
      iterations: Infinity,
      easing: 'ease-in-out'
    }
  )

  const right = rightEye.animate(
    [
      { transform: 'scale(1)' },
      { transform: 'scale(1.02, .98)' },
      { transform: 'scale(1)' }
    ],
    {
      duration: 2100,
      iterations: Infinity,
      easing: 'ease-in-out'
    }
  )

  const mouthAnimation = mouth.animate(
    playing
      ? [
          { transform: 'scale(1, .45)' },
          { transform: 'scale(.92, 1.35)' }
        ]
      : [
          { transform: 'scale(1)' },
          { transform: 'scale(.98, 1.05)' }
        ],
    {
      duration: playing ? 170 : 900,
      direction: 'alternate',
      iterations: Infinity,
      easing: 'ease-in-out'
    }
  )

  return () => {
    left.cancel()
    right.cancel()
    mouthAnimation.cancel()
  }
}