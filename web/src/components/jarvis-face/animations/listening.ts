import type { FaceElements, StopAnimation } from './types'
import { startIdleAnimation } from './idle'

// Restore the relaxed pre-redesign behaviour instead of the blue fixed stare.
export function startListeningAnimation(elements: FaceElements): StopAnimation {
  return startIdleAnimation(elements)
}
