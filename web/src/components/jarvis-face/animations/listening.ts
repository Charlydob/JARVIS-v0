import type { FaceElements, StopAnimation } from './types'
import { prefersReducedMotion } from './types'

export function startListeningAnimation(
  { leftEye, rightEye }: FaceElements
): StopAnimation {
  if (prefersReducedMotion()) return () => {}

  const left = leftEye.animate(
    [
      { transform: 'translateX(0) scale(1)' },
      { transform: 'translateX(5px) scale(1.07, 1.04)' },
      { transform: 'translateX(0) scale(1)' }
    ],
    {
      duration: 1800,
      iterations: Infinity,
      easing: 'cubic-bezier(.45,0,.55,1)'
    }
  )

  const right = rightEye.animate(
    [
      { transform: 'translateX(0) scale(1)' },
      { transform: 'translateX(-5px) scale(1.07, 1.04)' },
      { transform: 'translateX(0) scale(1)' }
    ],
    {
      duration: 1800,
      iterations: Infinity,
      easing: 'cubic-bezier(.45,0,.55,1)'
    }
  )

  return () => {
    left.cancel()
    right.cancel()
  }
}