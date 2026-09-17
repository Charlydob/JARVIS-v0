import type { FaceElements } from './types'

const ENTER_DURATION = 600
const BRAKE_DURATION = 420
const RETURN_DURATION = 430

const SPIN_SPEED = 0.01

const RIGHT_DELAY = 55
const LEFT_DELAY = 110

export const THINKING_EXIT_DURATION =
  BRAKE_DURATION + RETURN_DURATION

const n = (element: Element, attribute: string) =>
  parseFloat(element.getAttribute(attribute) ?? '0')

const lerp = (a: number, b: number, t: number) =>
  a + (b - a) * t

const easeIn = (t: number) =>
  t * t * t

const easeOut = (t: number) =>
  1 - Math.pow(1 - t, 5)

function animate(
  duration: number,
  callback: (progress: number, elapsed: number) => void
) {
  return new Promise<void>((resolve) => {
    const start = performance.now()

    function frame(now: number) {
      const elapsed = now - start
      const progress = Math.min(elapsed / duration, 1)

      callback(progress, elapsed)

      if (progress < 1) {
        requestAnimationFrame(frame)
      } else {
        resolve()
      }
    }

    requestAnimationFrame(frame)
  })
}

type Point = {
  x: number
  y: number
  r: number
}

function curve(
  start: { x: number; y: number },
  end: { x: number; y: number },
  t: number,
  bend = 70
) {
  const dx = end.x - start.x
  const dy = end.y - start.y

  const length = Math.hypot(dx, dy) || 1

  const middleX = (start.x + end.x) / 2
  const middleY = (start.y + end.y) / 2

  const controlX =
    middleX + (-dy / length) * bend

  const controlY =
    middleY + (dx / length) * bend

  const inverse = 1 - t

  return {
    x:
      inverse * inverse * start.x +
      2 * inverse * t * controlX +
      t * t * end.x,

    y:
      inverse * inverse * start.y +
      2 * inverse * t * controlY +
      t * t * end.y
  }
}

function setCircle(
  element: SVGCircleElement,
  x: number,
  y: number,
  r: number
) {
  element.setAttribute('cx', String(x))
  element.setAttribute('cy', String(y))
  element.setAttribute('r', String(r))
}

function setMouth(
  mouth: SVGRectElement,
  x: number,
  y: number,
  width: number,
  height: number,
  rx: number,
  ry: number
) {
  mouth.setAttribute('x', String(x - width / 2))
  mouth.setAttribute('y', String(y - height / 2))
  mouth.setAttribute('width', String(width))
  mouth.setAttribute('height', String(height))
  mouth.setAttribute('rx', String(rx))
  mouth.setAttribute('ry', String(ry))
}

function readPoint(circle: SVGCircleElement): Point {
  return {
    x: n(circle, 'cx'),
    y: n(circle, 'cy'),
    r: n(circle, 'r')
  }
}

export async function runThinkingAnimation(
  elements: FaceElements,
  signal: AbortSignal
) {
  const {
    svg,
    leftEye,
    rightEye,
    mouth
  } = elements

  const guide =
    svg.querySelector<SVGCircleElement>(
      '#thinking-orbit-guide'
    )

  const dotTop =
    svg.querySelector<SVGCircleElement>(
      '#thinking-dot-1'
    )

  const dotRight =
    svg.querySelector<SVGCircleElement>(
      '#thinking-dot-2'
    )

  const dotLeft =
    svg.querySelector<SVGCircleElement>(
      '#thinking-dot-3'
    )

  if (!guide || !dotTop || !dotRight || !dotLeft) {
    console.warn('Faltan referencias de Thinking en FaceSvg')
    return
  }

  const idle = {
    left: {
      x: n(leftEye, 'cx'),
      y: n(leftEye, 'cy'),
      r: n(leftEye, 'r')
    },

    right: {
      x: n(rightEye, 'cx'),
      y: n(rightEye, 'cy'),
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

  const center = {
    x: n(guide, 'cx'),
    y: n(guide, 'cy')
  }

  const target = {
    left: readPoint(dotLeft),
    right: readPoint(dotRight),
    mouth: readPoint(dotTop)
  }

  const mouthStart = {
    x: idle.mouth.x + idle.mouth.width / 2,
    y: idle.mouth.y + idle.mouth.height / 2
  }

  /* CARA → PUNTOS */

  await animate(ENTER_DURATION, (raw) => {
    const t = easeIn(raw)

    const left = curve(
      idle.left,
      target.left,
      t,
      70
    )

    const right = curve(
      idle.right,
      target.right,
      t,
      70
    )

    const mouthPosition = curve(
      mouthStart,
      target.mouth,
      t,
      90
    )

    setCircle(
      leftEye,
      left.x,
      left.y,
      lerp(idle.left.r, target.left.r, t)
    )

    setCircle(
      rightEye,
      right.x,
      right.y,
      lerp(idle.right.r, target.right.r, t)
    )

    const width = lerp(
      idle.mouth.width,
      target.mouth.r * 2,
      t
    )

    const height = lerp(
      idle.mouth.height,
      target.mouth.r * 2,
      t
    )

    setMouth(
      mouth,
      mouthPosition.x,
      mouthPosition.y,
      width,
      height,
      lerp(idle.mouth.rx, target.mouth.r, t),
      lerp(idle.mouth.ry, target.mouth.r, t)
    )

  })

  if (signal.aborted) {
    await returnToIdle(elements, idle)
    return
  }

  function orbitInfo(point: Point) {
    return {
      angle: Math.atan2(
        point.y - center.y,
        point.x - center.x
      ),

      radius: Math.hypot(
        point.x - center.x,
        point.y - center.y
      ),

      dotRadius: point.r
    }
  }

  const orbit = {
    left: orbitInfo(target.left),
    right: orbitInfo(target.right),
    mouth: orbitInfo(target.mouth)
  }

  const rotations = {
    mouth: 0,
    right: 0,
    left: 0
  }

  function orbitPosition(
    info: ReturnType<typeof orbitInfo>,
    rotation: number
  ) {
    const angle = info.angle + rotation

    return {
      x:
        center.x +
        Math.cos(angle) * info.radius,

      y:
        center.y +
        Math.sin(angle) * info.radius
    }
  }

  function drawOrbit() {
    const left = orbitPosition(
      orbit.left,
      rotations.left
    )

    const right = orbitPosition(
      orbit.right,
      rotations.right
    )

    const mouthPosition = orbitPosition(
      orbit.mouth,
      rotations.mouth
    )

    setCircle(
      leftEye,
      left.x,
      left.y,
      orbit.left.dotRadius
    )

    setCircle(
      rightEye,
      right.x,
      right.y,
      orbit.right.dotRadius
    )

    setMouth(
      mouth,
      mouthPosition.x,
      mouthPosition.y,
      orbit.mouth.dotRadius * 2,
      orbit.mouth.dotRadius * 2,
      orbit.mouth.dotRadius,
      orbit.mouth.dotRadius
    )
  }

  /* GIRAR HASTA QUE JARVIS DEJE DE PENSAR */

  await new Promise<void>((resolve) => {
    const start = performance.now()

    function frame(now: number) {
      const elapsed = now - start

      rotations.mouth =
        elapsed * SPIN_SPEED

      rotations.right =
        Math.max(0, elapsed - RIGHT_DELAY) *
        SPIN_SPEED

      rotations.left =
        Math.max(0, elapsed - LEFT_DELAY) *
        SPIN_SPEED

      drawOrbit()

      if (signal.aborted) {
        resolve()
        return
      }

      requestAnimationFrame(frame)
    }

    requestAnimationFrame(frame)
  })

  /* FRENADA */

  const rotationStart = {
    ...rotations
  }

  const extraRotation =
    SPIN_SPEED *
    BRAKE_DURATION *
    0.5

  await animate(BRAKE_DURATION, (raw) => {
    const t = easeOut(raw)

    rotations.mouth =
      rotationStart.mouth +
      extraRotation * t

    rotations.right =
      rotationStart.right +
      extraRotation * t

    rotations.left =
      rotationStart.left +
      extraRotation * t

    drawOrbit()
  })

  /* PUNTOS → CARA */

  await returnToIdle(elements, idle)
}

async function returnToIdle(
  { leftEye, rightEye, mouth }: FaceElements,
  idle: {
    left: { x: number; y: number; r: number }
    right: { x: number; y: number; r: number }
    mouth: {
      x: number
      y: number
      width: number
      height: number
      rx: number
      ry: number
    }
  }
) {
  const leftStart = {
    x: n(leftEye, 'cx'),
    y: n(leftEye, 'cy'),
    r: n(leftEye, 'r')
  }

  const rightStart = {
    x: n(rightEye, 'cx'),
    y: n(rightEye, 'cy'),
    r: n(rightEye, 'r')
  }

  const mouthStart = {
    x: n(mouth, 'x') + n(mouth, 'width') / 2,
    y: n(mouth, 'y') + n(mouth, 'height') / 2,
    width: n(mouth, 'width'),
    height: n(mouth, 'height'),
    rx: n(mouth, 'rx'),
    ry: n(mouth, 'ry')
  }

  const mouthEnd = {
    x: idle.mouth.x + idle.mouth.width / 2,
    y: idle.mouth.y + idle.mouth.height / 2
  }

  await animate(RETURN_DURATION, (raw) => {
    const t = easeOut(raw)

    const left = curve(
      leftStart,
      idle.left,
      t,
      -70
    )

    const right = curve(
      rightStart,
      idle.right,
      t,
      -70
    )

    const mouthPosition = curve(
      mouthStart,
      mouthEnd,
      t,
      -90
    )

    setCircle(
      leftEye,
      left.x,
      left.y,
      lerp(leftStart.r, idle.left.r, t)
    )

    setCircle(
      rightEye,
      right.x,
      right.y,
      lerp(rightStart.r, idle.right.r, t)
    )

    setMouth(
      mouth,
      mouthPosition.x,
      mouthPosition.y,
      lerp(
        mouthStart.width,
        idle.mouth.width,
        t
      ),
      lerp(
        mouthStart.height,
        idle.mouth.height,
        t
      ),
      lerp(
        mouthStart.rx,
        idle.mouth.rx,
        t
      ),
      lerp(
        mouthStart.ry,
        idle.mouth.ry,
        t
      )
    )
  })

  setCircle(
    leftEye,
    idle.left.x,
    idle.left.y,
    idle.left.r
  )

  setCircle(
    rightEye,
    idle.right.x,
    idle.right.y,
    idle.right.r
  )

  setMouth(
    mouth,
    idle.mouth.x + idle.mouth.width / 2,
    idle.mouth.y + idle.mouth.height / 2,
    idle.mouth.width,
    idle.mouth.height,
    idle.mouth.rx,
    idle.mouth.ry
  )

  mouth.removeAttribute('transform')
}