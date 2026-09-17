import type { FaceElements, StopAnimation } from './types'
import { prefersReducedMotion } from './types'

export function startIdleAnimation(
  { svg, leftEye, rightEye, mouth }: FaceElements
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

  const drift = svg.animate(
    [
      { transform: 'translate3d(-22px, 5px, 0) rotate(-.6deg)' },
      { transform: 'translate3d(26px, -10px, 0) rotate(.55deg)', offset: .36 },
      { transform: 'translate3d(8px, 8px, 0) rotate(.15deg)', offset: .7 },
      { transform: 'translate3d(-22px, 5px, 0) rotate(-.6deg)' }
    ],
    { duration: 9000, iterations: Infinity, easing: 'cubic-bezier(.45,0,.55,1)' }
  )

  return () => {
    left.cancel()
    right.cancel()
    mouthAnimation.cancel()
    drift.cancel()
  }
}
