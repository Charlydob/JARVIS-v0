import type { FaceElements, StopAnimation } from './types'
import { prefersReducedMotion } from './types'

const n = (element: Element, attribute: string) =>
  parseFloat(element.getAttribute(attribute) ?? '0')

function lineToCircle(
  circle: SVGCircleElement,
  targetPath: SVGPathElement
) {
  circle.style.opacity = '0'
  targetPath.style.opacity = '1'
}

export function startErrorAnimation(
  { svg, leftEye, rightEye, mouth }: FaceElements
): StopAnimation {
  const leftX = svg.querySelector<SVGPathElement>('#error-eye-left')
  const rightX = svg.querySelector<SVGPathElement>('#error-eye-right')
  const errorMouth = svg.querySelector<SVGPathElement>('#error-mouth')

  if (!leftX || !rightX || !errorMouth) {
    console.warn('Faltan referencias Error en FaceSvg')
    return () => {}
  }

  const originalMouth = {
    x: n(mouth, 'x'),
    y: n(mouth, 'y'),
    width: n(mouth, 'width'),
    height: n(mouth, 'height'),
    rx: n(mouth, 'rx'),
    ry: n(mouth, 'ry')
  }

  leftX.style.display = 'inline'
  rightX.style.display = 'inline'
  errorMouth.style.display = 'inline'

  lineToCircle(leftEye, leftX)
  lineToCircle(rightEye, rightX)

  mouth.style.opacity = '0'
  errorMouth.style.opacity = '1'
  leftX.style.opacity = '1'
  rightX.style.opacity = '1'

  const animations: Animation[] = []

  if (!prefersReducedMotion()) {
    animations.push(
      svg.animate(
        [
          { transform: 'translateX(0px)' },
          { transform: 'translateX(-6px)' },
          { transform: 'translateX(6px)' },
          { transform: 'translateX(-4px)' },
          { transform: 'translateX(4px)' },
          { transform: 'translateX(0px)' }
        ],
        {
          duration: 520,
          iterations: Infinity,
          easing: 'ease-in-out'
        }
      )
    )
  }

  return () => {
    for (const animation of animations) animation.cancel()

    svg.style.transform = ''

    leftEye.style.opacity = '1'
    rightEye.style.opacity = '1'
    mouth.style.opacity = '1'

    leftX.style.opacity = '0'
    rightX.style.opacity = '0'
    errorMouth.style.opacity = '0'

    mouth.setAttribute('x', String(originalMouth.x))
    mouth.setAttribute('y', String(originalMouth.y))
    mouth.setAttribute('width', String(originalMouth.width))
    mouth.setAttribute('height', String(originalMouth.height))
    mouth.setAttribute('rx', String(originalMouth.rx))
    mouth.setAttribute('ry', String(originalMouth.ry))
  }
}