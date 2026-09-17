import type { FaceElements, StopAnimation } from './types'
import { prefersReducedMotion } from './types'

export function startErrorAnimation(
  { svg, mouth }: FaceElements
): StopAnimation {
  if (prefersReducedMotion()) return () => {}

  const shake = svg.animate(
    [
      { transform: 'translateX(0)' },
      { transform: 'translateX(-6px)' },
      { transform: 'translateX(6px)' },
      { transform: 'translateX(-4px)' },
      { transform: 'translateX(4px)' },
      { transform: 'translateX(0)' }
    ],
    {
      duration: 550,
      iterations: Infinity,
      easing: 'ease-in-out'
    }
  )

  const mouthAnimation = mouth.animate(
    [{ transform: 'rotate(180deg)' }],
    {
      duration: 1,
      fill: 'forwards'
    }
  )

  return () => {
    shake.cancel()
    mouthAnimation.cancel()
  }
}