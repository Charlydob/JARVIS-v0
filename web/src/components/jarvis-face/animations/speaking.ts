import type { FaceElements, StopAnimation } from './types'
import { prefersReducedMotion } from './types'

const n = (element: Element, attribute: string) =>
  parseFloat(element.getAttribute(attribute) ?? '0')

function setMouth(
  mouth: SVGRectElement,
  x: number,
  y: number,
  width: number,
  height: number,
  rx: number,
  ry: number
) {
  mouth.setAttribute('x', String(x))
  mouth.setAttribute('y', String(y))
  mouth.setAttribute('width', String(width))
  mouth.setAttribute('height', String(height))
  mouth.setAttribute('rx', String(rx))
  mouth.setAttribute('ry', String(ry))
}

type MouthPose = {
  x: number
  y: number
  width: number
  height: number
  rx: number
  ry: number
}

function readRect(rect: SVGRectElement): MouthPose {
  return {
    x: n(rect, 'x'),
    y: n(rect, 'y'),
    width: n(rect, 'width'),
    height: n(rect, 'height'),
    rx: n(rect, 'rx'),
    ry: n(rect, 'ry')
  }
}

export function startSpeakingAnimation(
  { svg, leftEye, rightEye, mouth }: FaceElements,
  playing: boolean
): StopAnimation {
  const closedRef = svg.querySelector<SVGRectElement>('#speaking-mouth-closed')
  const mediumRef = svg.querySelector<SVGRectElement>('#speaking-mouth-medium')
  const openRef = svg.querySelector<SVGRectElement>('#speaking-mouth-open')

  if (!closedRef || !mediumRef || !openRef) {
    console.warn('Faltan referencias Speaking en FaceSvg')
    return () => {}
  }

  const original = {
    x: n(mouth, 'x'),
    y: n(mouth, 'y'),
    width: n(mouth, 'width'),
    height: n(mouth, 'height'),
    rx: n(mouth, 'rx'),
    ry: n(mouth, 'ry')
  }

  const closed = readRect(closedRef)
  const medium = readRect(mediumRef)
  const open = readRect(openRef)

  const animations: Animation[] = []

  if (!prefersReducedMotion()) {
    animations.push(
      leftEye.animate(
        [
          { transform: 'scale(1)' },
          { transform: 'scale(.985, 1.02)' },
          { transform: 'scale(1)' }
        ],
        {
          duration: 2800,
          iterations: Infinity,
          easing: 'ease-in-out'
        }
      )
    )

    animations.push(
      rightEye.animate(
        [
          { transform: 'scale(1)' },
          { transform: 'scale(1.015, .985)' },
          { transform: 'scale(1)' }
        ],
        {
          duration: 2600,
          iterations: Infinity,
          easing: 'ease-in-out'
        }
      )
    )

    animations.push(
      svg.animate(
        [
          { transform: 'translateY(0px)' },
          { transform: 'translateY(3px)' },
          { transform: 'translateY(0px)' }
        ],
        {
          duration: 1900,
          iterations: Infinity,
          easing: 'ease-in-out'
        }
      )
    )

    if (playing) {
      animations.push(
        mouth.animate(
          [
            closed,
            medium,
            open,
            medium,
            closed,
            medium,
            closed
          ],
          {
            duration: 820,
            iterations: Infinity,
            easing: 'linear'
          }
        )
      )
    } else {
      animations.push(
        mouth.animate(
          [closed, medium, closed],
          {
            duration: 1400,
            iterations: Infinity,
            easing: 'ease-in-out'
          }
        )
      )
    }
  }

  setMouth(
    mouth,
    closed.x,
    closed.y,
    closed.width,
    closed.height,
    closed.rx,
    closed.ry
  )

  return () => {
    for (const animation of animations) animation.cancel()

    leftEye.style.transform = ''
    rightEye.style.transform = ''
    svg.style.transform = ''

    setMouth(
      mouth,
      original.x,
      original.y,
      original.width,
      original.height,
      original.rx,
      original.ry
    )
  }
}