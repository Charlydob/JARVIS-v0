import { describe, expect, it, vi } from 'vitest'
import type { JarvisState } from '../../../state/machine'
import type { FaceElements } from './types'
import { CANONICAL_FACE, canonicalGeometry, resetFaceToCanonicalState } from './canonical'

function element(attributes: Record<string, string> = {}) {
  const values = new Map(Object.entries(attributes))
  return {
    style: { transform: '', opacity: '' },
    getAttribute: (name: string) => values.get(name) ?? null,
    setAttribute: (name: string, value: string) => values.set(name, value),
    removeAttribute: (name: string) => values.delete(name),
    getAnimations: () => [{ cancel: vi.fn() }],
  }
}

function face(): FaceElements {
  const helpers = new Map([
    ['#sleeping-zzz', element()], ['#error-eye-left', element()],
    ['#error-eye-right', element()], ['#error-mouth', element()],
  ])
  const svg = {
    ...element(),
    querySelectorAll: () => [...helpers.values()],
    querySelector: (selector: string) => helpers.get(selector) ?? null,
  }
  return {
    svg: svg as unknown as SVGSVGElement,
    leftEye: element() as unknown as SVGCircleElement,
    rightEye: element() as unknown as SVGCircleElement,
    mouth: element() as unknown as SVGRectElement,
  }
}

describe('canonical face reset', () => {
  it('survives 50 interrupted state cycles without cumulative deformation', () => {
    const elements = face()
    const states: JarvisState[] = ['idle', 'listening', 'thinking', 'speaking']
    for (let index = 0; index < 50; index += 1) {
      elements.leftEye.setAttribute('cx', String(index * 91))
      elements.rightEye.setAttribute('r', String(index + 1))
      elements.mouth.setAttribute('width', String(index * 7))
      elements.svg.style.transform = `translateX(${index}px)`
      resetFaceToCanonicalState(elements, states[index % states.length])
      expect(canonicalGeometry(elements)).toEqual(CANONICAL_FACE)
      expect(elements.svg.style.transform).toBe('')
    }
  })
})
