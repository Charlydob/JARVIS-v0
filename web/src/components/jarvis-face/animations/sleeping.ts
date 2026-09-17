import type { FaceElements, StopAnimation } from './types'
import { prefersReducedMotion } from './types'

const n = (element: Element, attribute: string) =>
  parseFloat(element.getAttribute(attribute) ?? '0')

function setRect(
  rect: SVGRectElement,
  x: number,
  y: number,
  width: number,
  height: number,
  rx: number,
  ry: number
) {
  rect.setAttribute('x', String(x))
  rect.setAttribute('y', String(y))
  rect.setAttribute('width', String(width))
  rect.setAttribute('height', String(height))
  rect.setAttribute('rx', String(rx))
  rect.setAttribute('ry', String(ry))
}

export function startSleepingAnimation(
  { svg, leftEye, rightEye, mouth }: FaceElements
): StopAnimation {
  const leftRef = svg.querySelector<SVGRectElement>('#sleeping-eye-left')
  const rightRef = svg.querySelector<SVGRectElement>('#sleeping-eye-right')
  const mouthRef = svg.querySelector<SVGRectElement>('#sleeping-mouth')
  const zzz = svg.querySelector<SVGGElement>('#sleeping-zzz')

  if (!leftRef || !rightRef || !mouthRef || !zzz) {
    console.warn('Faltan referencias Sleeping en FaceSvg')
    return () => {}
  }

  const original = {
    left: {
      cx: n(leftEye, 'cx'),
      cy: n(leftEye, 'cy'),
      r: n(leftEye, 'r')
    },
    right: {
      cx: n(rightEye, 'cx'),
      cy: n(rightEye, 'cy'),
      r: n(rightEye, 'r')
    },
    mouth: {
      x: n(mouth, 'x'),
      y: n(mouth, 'y'),
      width: n(mouth, 'width'),
      height: n(mouth, 'height'),
      rx: n(mouth, 'rx'),
      ry: n(mouth, 'ry')
    }
  }

  // Ojos cerrados = escalamos los círculos para parecer cápsulas
  leftEye.style.transform = 'scale(1, .15)'
  rightEye.style.transform = 'scale(1, .15)'

  setRect(
    mouth,
    n(mouthRef, 'x'),
    n(mouthRef, 'y'),
    n(mouthRef, 'width'),
    n(mouthRef, 'height'),
    n(mouthRef, 'rx'),
    n(mouthRef, 'ry')
  )

  const animations: Animation[] = []

  zzz.style.opacity = '1'

  if (!prefersReducedMotion()) {
    animations.push(
      svg.animate(
        [
          { transform: 'translateY(0px) scale(1)' },
          { transform: 'translateY(8px) scale(1.01)' },
          { transform: 'translateY(0px) scale(1)' }
        ],
        {
          duration: 3200,
          iterations: Infinity,
          easing: 'ease-in-out'
        }
      )
    )

    animations.push(
      zzz.animate(
        [
          { opacity: 0.3, transform: 'translateY(6px)' },
          { opacity: 1, transform: 'translateY(-8px)' },
          { opacity: 0.45, transform: 'translateY(-18px)' }
        ],
        {
          duration: 2600,
          iterations: Infinity,
          easing: 'ease-in-out'
        }
      )
    )
  }

  return () => {
    for (const animation of animations) animation.cancel()

    zzz.style.opacity = '0'
    zzz.style.transform = ''

    svg.style.transform = ''
    leftEye.style.transform = ''
    rightEye.style.transform = ''

    leftEye.setAttribute('cx', String(original.left.cx))
    leftEye.setAttribute('cy', String(original.left.cy))
    leftEye.setAttribute('r', String(original.left.r))

    rightEye.setAttribute('cx', String(original.right.cx))
    rightEye.setAttribute('cy', String(original.right.cy))
    rightEye.setAttribute('r', String(original.right.r))

    setRect(
      mouth,
      original.mouth.x,
      original.mouth.y,
      original.mouth.width,
      original.mouth.height,
      original.mouth.rx,
      original.mouth.ry
    )
  }
}