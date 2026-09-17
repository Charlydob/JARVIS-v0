import type { FaceElements, StopAnimation } from './types'
import { prefersReducedMotion } from './types'

export function startIdleAnimation(
  { leftEye, rightEye, mouth }: FaceElements
): StopAnimation {
  if (prefersReducedMotion()) return () => {}

  const eyeFrames: Keyframe[] = [
    { transform: 'scale(1)', offset: 0 },
    { transform: 'scale(1.025, .97)', offset: 0.15 },
    { transform: 'scale(1)', offset: 0.42 },
    { transform: 'scaleY(.08)', offset: 0.465 },
    { transform: 'scale(1)', offset: 0.49 },
    { transform: 'scale(.975, 1.025)', offset: 0.72 },
    { transform: 'scale(1)', offset: 1 }
  ]

  const left = leftEye.animate(eyeFrames, {
    duration: 6800,
    iterations: Infinity,
    easing: 'cubic-bezier(.45,0,.55,1)'
  })

  const right = rightEye.animate(eyeFrames, {
    duration: 6800,
    delay: -120,
    iterations: Infinity,
    easing: 'cubic-bezier(.45,0,.55,1)'
  })

  const mouthAnimation = mouth.animate(
    [
      { transform: 'scale(1, .96)' },
      { transform: 'scale(.98, 1.06)' },
      { transform: 'scale(1, .96)' }
    ],
    {
      duration: 4800,
      iterations: Infinity,
      easing: 'cubic-bezier(.45,0,.55,1)'
    }
  )

  return () => {
    left.cancel()
    right.cancel()
    mouthAnimation.cancel()
  }
}