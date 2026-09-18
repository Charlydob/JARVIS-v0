import type { JarvisState } from '../../../state/machine'
import type { FaceElements } from './types'

export const CANONICAL_FACE = Object.freeze({
  leftEye: Object.freeze({ cx: '350', cy: '360', r: '60' }),
  rightEye: Object.freeze({ cx: '650', cy: '360', r: '60' }),
  mouth: Object.freeze({ x: '410', y: '520', width: '180', height: '40', rx: '18.897638', ry: '18.897638' })
})

const setAttributes = (element: Element, attributes: Record<string, string>) => {
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value)
  element.removeAttribute('transform')
}

/** Synchronously removes every prior animation and restores the SVG source geometry. */
export function resetFaceToCanonicalState(
  { svg, leftEye, rightEye, mouth }: FaceElements,
  state: JarvisState
) {
  void state
  for (const element of [svg, leftEye, rightEye, mouth, ...Array.from(svg.querySelectorAll('*'))]) {
    element.getAnimations?.().forEach((animation) => animation.cancel())
  }

  svg.style.transform = ''
  leftEye.style.transform = ''
  rightEye.style.transform = ''
  mouth.style.transform = ''
  leftEye.style.opacity = '1'
  rightEye.style.opacity = '1'
  mouth.style.opacity = '1'

  setAttributes(leftEye, CANONICAL_FACE.leftEye)
  setAttributes(rightEye, CANONICAL_FACE.rightEye)
  setAttributes(mouth, CANONICAL_FACE.mouth)

  const zzz = svg.querySelector<SVGElement>('#sleeping-zzz')
  if (zzz) { zzz.style.opacity = '0'; zzz.style.transform = '' }
  for (const selector of ['#error-eye-left', '#error-eye-right', '#error-mouth']) {
    const element = svg.querySelector<SVGElement>(selector)
    if (element) { element.style.opacity = '0'; element.style.transform = '' }
  }
}

export function canonicalGeometry({ leftEye, rightEye, mouth }: FaceElements) {
  return {
    leftEye: { cx: leftEye.getAttribute('cx'), cy: leftEye.getAttribute('cy'), r: leftEye.getAttribute('r') },
    rightEye: { cx: rightEye.getAttribute('cx'), cy: rightEye.getAttribute('cy'), r: rightEye.getAttribute('r') },
    mouth: {
      x: mouth.getAttribute('x'), y: mouth.getAttribute('y'), width: mouth.getAttribute('width'),
      height: mouth.getAttribute('height'), rx: mouth.getAttribute('rx'), ry: mouth.getAttribute('ry')
    }
  }
}
