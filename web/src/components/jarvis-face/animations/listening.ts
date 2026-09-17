import type {
  FaceElements,
  StopAnimation
} from './types'

import {
  prefersReducedMotion
} from './types'

const ENTER_DURATION = 280

const randomBetween = (
  min: number,
  max: number
) =>
  min + Math.random() * (max - min)

const n = (
  element: Element,
  attribute: string
) =>
  parseFloat(
    element.getAttribute(attribute) ?? '0'
  )

const lerp = (
  a: number,
  b: number,
  t: number
) =>
  a + (b - a) * t

const easeOut = (t: number) =>
  1 - Math.pow(1 - t, 4)

export function startListeningAnimation(
  {
    svg,
    leftEye,
    rightEye,
    mouth
  }: FaceElements
): StopAnimation {

  /*
    =============================
    LEER REFERENCIAS DEL SVG
    =============================
  */

  const refLeft =
    svg.querySelector<SVGEllipseElement>(
      '#listening-eye-left'
    )

  const refRight =
    svg.querySelector<SVGEllipseElement>(
      '#listening-eye-right'
    )

  const refMouth =
    svg.querySelector<SVGRectElement>(
      '#listening-mouth'
    )

  const colorPeak =
    svg.querySelector<SVGCircleElement>(
      '#listening-color-peak'
    )

  if (
    !refLeft ||
    !refRight ||
    !refMouth ||
    !colorPeak
  ) {
    console.warn(
      'Faltan referencias Listening en FaceSvg'
    )

    return () => {}
  }
const listeningMouth = {
  x: listeningMouth.x,
  y: listeningMouth.y,
  width: listeningMouth.width,
  height: listeningMouth.height,
  rx: listeningMouth.rx,
  ry: listeningMouth.ry
}
  /*
    =============================
    GUARDAR ESTADO ORIGINAL
    =============================
  */

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

  /*
    Escala necesaria para transformar
    los círculos originales en los
    ojos verticales diseñados.
  */

  const leftScaleX =
    n(refLeft, 'rx') /
    original.left.r

  const leftScaleY =
    n(refLeft, 'ry') /
    original.left.r

  const rightScaleX =
    n(refRight, 'rx') /
    original.right.r

  const rightScaleY =
    n(refRight, 'ry') /
    original.right.r

  const baseColor =
    refLeft.getAttribute('fill') ??
    '#DFF6FF'

  const peakColor =
    colorPeak.getAttribute('fill') ??
    '#7FDBFF'

  let cancelled = false

  let entryFrame = 0

  let blinkTimer:
    number | undefined

  let nodTimer:
    number | undefined

  const animations: Animation[] = []

  /*
    =============================
    BOCA → LISTENING
    =============================
  */

  const entryStart =
    performance.now()

  function animateEntry(now: number) {
    if (cancelled) return

    const raw = Math.min(
      (now - entryStart) /
      ENTER_DURATION,
      1
    )

    const t =
      easeOut(raw)

    mouth.setAttribute(
      'x',
      String(
        lerp(
          original.mouth.x,
          listeningMouth.x,
          t
        )
      )
    )

    mouth.setAttribute(
      'y',
      String(
        lerp(
          original.mouth.y,
          listeningMouth.y,
          t
        )
      )
    )

    mouth.setAttribute(
      'width',
      String(
        lerp(
          original.mouth.width,
          listeningMouth.width,
          t
        )
      )
    )

    mouth.setAttribute(
      'height',
      String(
        lerp(
          original.mouth.height,
          listeningMouth.height,
          t
        )
      )
    )

    mouth.setAttribute(
      'rx',
      String(
        lerp(
          original.mouth.rx,
          listeningMouth.rx,
          t
        )
      )
    )

    mouth.setAttribute(
      'ry',
      String(
        lerp(
          original.mouth.ry,
          listeningMouth.ry,
          t
        )
      )
    )

    if (raw < 1) {
      entryFrame =
        requestAnimationFrame(
          animateEntry
        )
    }
  }

  entryFrame =
    requestAnimationFrame(
      animateEntry
    )

  /*
    =============================
    FORMA DE LOS OJOS
    =============================
  */

  leftEye.style.transform =
    `scale(${leftScaleX}, ${leftScaleY})`

  rightEye.style.transform =
    `scale(${rightScaleX}, ${rightScaleY})`

  /*
    =============================
    PULSO AZUL
    =============================
  */

  if (!prefersReducedMotion()) {

    const pulseOptions:
      KeyframeAnimationOptions = {
        duration: 1600,
        iterations: Infinity,
        easing:
          'cubic-bezier(.45,0,.55,1)'
      }

    animations.push(
      leftEye.animate(
        [
          { fill: baseColor },
          { fill: peakColor },
          { fill: baseColor }
        ],
        pulseOptions
      )
    )

    animations.push(
      rightEye.animate(
        [
          { fill: baseColor },
          { fill: peakColor },
          { fill: baseColor }
        ],
        {
          ...pulseOptions,
          delay: 80
        }
      )
    )
  }

  /*
    =============================
    PARPADEOS NATURALES
    =============================
  */

  function blink() {
    if (
      cancelled ||
      prefersReducedMotion()
    ) {
      return
    }

    const leftBlink =
      leftEye.animate(
        [
          {
            transform:
              `scale(${leftScaleX}, ${leftScaleY})`
          },
          {
            transform:
              `scale(${leftScaleX}, 0.08)`
          },
          {
            transform:
              `scale(${leftScaleX}, ${leftScaleY})`
          }
        ],
        {
          duration: 180,
          easing:
            'cubic-bezier(.4,0,.2,1)'
        }
      )

    /*
      El segundo ojo cierra
      unas décimas después.
      Da menos sensación robótica.
    */

    const rightBlink =
      rightEye.animate(
        [
          {
            transform:
              `scale(${rightScaleX}, ${rightScaleY})`
          },
          {
            transform:
              `scale(${rightScaleX}, 0.08)`
          },
          {
            transform:
              `scale(${rightScaleX}, ${rightScaleY})`
          }
        ],
        {
          duration: 180,
          delay: 35,
          easing:
            'cubic-bezier(.4,0,.2,1)'
        }
      )

    animations.push(
      leftBlink,
      rightBlink
    )

    scheduleBlink()
  }

  function scheduleBlink() {
    if (cancelled) return

    blinkTimer =
      window.setTimeout(
        blink,
        randomBetween(
          2300,
          5200
        )
      )
  }

  /*
    =============================
    ESCUCHA ACTIVA / ASENTIR
    =============================
  */

  function nod() {
    if (
      cancelled ||
      prefersReducedMotion()
    ) {
      return
    }

    /*
      Se acerca ligeramente,
      baja como asintiendo,
      retrocede un pelín
      y vuelve a posición.
    */

    const animation =
      svg.animate(
        [
          {
            transform:
              'translateY(3px) scale(1.012)'
          },

          {
            transform:
              'translateY(11px) scale(1.022)',
            offset: 0.32
          },

          {
            transform:
              'translateY(-1px) scale(.998)',
            offset: 0.67
          },

          {
            transform:
              'translateY(3px) scale(1.012)'
          }
        ],
        {
          duration:
            randomBetween(
              650,
              850
            ),

          easing:
            'cubic-bezier(.34,1.56,.64,1)'
        }
      )

    animations.push(animation)

    scheduleNod()
  }

  function scheduleNod() {
    if (cancelled) return

    nodTimer =
      window.setTimeout(
        nod,
        randomBetween(
          2000,
          3500
        )
      )
  }

  /*
    Postura base:
    un poquito más cerca
    que Idle.
  */

  svg.style.transform =
    'translateY(3px) scale(1.012)'

  if (!prefersReducedMotion()) {
    scheduleBlink()
    scheduleNod()
  }

  /*
    =============================
    CLEANUP
    =============================
  */

  return () => {
    cancelled = true

    cancelAnimationFrame(
      entryFrame
    )

    if (blinkTimer !== undefined) {
      window.clearTimeout(
        blinkTimer
      )
    }

    if (nodTimer !== undefined) {
      window.clearTimeout(
        nodTimer
      )
    }

    for (
      const animation
      of animations
    ) {
      animation.cancel()
    }

    /*
      Restauramos completamente
      Idle para que THINKING
      pueda leer sus coordenadas
      correctamente.
    */

    leftEye.style.transform = ''
    rightEye.style.transform = ''

    leftEye.style.fill = ''
    rightEye.style.fill = ''

    svg.style.transform = ''

    leftEye.setAttribute(
      'cx',
      String(original.left.cx)
    )

    leftEye.setAttribute(
      'cy',
      String(original.left.cy)
    )

    leftEye.setAttribute(
      'r',
      String(original.left.r)
    )

    rightEye.setAttribute(
      'cx',
      String(original.right.cx)
    )

    rightEye.setAttribute(
      'cy',
      String(original.right.cy)
    )

    rightEye.setAttribute(
      'r',
      String(original.right.r)
    )

    mouth.setAttribute(
      'x',
      String(original.mouth.x)
    )

    mouth.setAttribute(
      'y',
      String(original.mouth.y)
    )

    mouth.setAttribute(
      'width',
      String(original.mouth.width)
    )

    mouth.setAttribute(
      'height',
      String(original.mouth.height)
    )

    mouth.setAttribute(
      'rx',
      String(original.mouth.rx)
    )

    mouth.setAttribute(
      'ry',
      String(original.mouth.ry)
    )
  }
}