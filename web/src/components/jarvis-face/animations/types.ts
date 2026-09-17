export type FaceElements = {
  svg: SVGSVGElement
  leftEye: SVGCircleElement
  rightEye: SVGCircleElement
  mouth: SVGRectElement
}

export type StopAnimation = () => void

export function prefersReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}