import { describe, expect, it } from 'vitest'
import { versionDisplayLines } from './versionDisplay'

describe('version display', () => {
  it('shows one compact line when web and core match', () => {
    expect(versionDisplayLines(
      { version: '0.4.0', buildSha: 'abcdef123456' },
      { version: '0.4.0', buildSha: 'abcdef123456' },
    )).toEqual(['JARVIS v0.4.0 · abcdef1'])
  })

  it('shows both runtimes when their builds differ', () => {
    expect(versionDisplayLines(
      { version: '0.4.0', buildSha: 'abcdef123456' },
      { version: '0.4.0', buildSha: '7654321fedcb' },
    )).toEqual(['WEB v0.4.0 · abcdef1', 'CORE v0.4.0 · 7654321'])
  })
})
