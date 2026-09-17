import type { FaceElements, StopAnimation } from './types'

export function startSleepingAnimation(
  { leftEye, rightEye, mouth }: FaceElements
): StopAnimation {
  const options: KeyframeAnimationOptions = {
    duration: 350,
    fill: 'forwards',
    easing: 'cubic-bezier(.16,1,.3,1)'
  }

  const left = leftEye.animate(
    [{ transform: 'scaleY(1)' }, { transform: 'scaleY(.12)' }],
    options
  )

  const right = rightEye.animate(
    [{ transform: 'scaleY(1)' }, { transform: 'scaleY(.12)' }],
    options
  )

  const mouthAnimation = mouth.animate(
    [{ transform: 'scaleY(1)' }, { transform: 'scaleY(.25)' }],
    options
  )

  return () => {
    left.cancel()
    right.cancel()
    mouthAnimation.cancel()
  }
}