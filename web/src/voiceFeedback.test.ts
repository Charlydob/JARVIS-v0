import { describe, expect, it } from 'vitest'
import { parseVoiceFeedback } from './voiceFeedback'

describe('voice feedback', () => {
  it('extracts a conservative negative correction', () => {
    const transcript = 'No Jarvis, respuesta incorrecta. No has buscado en BookShell. Deberías haber consultado mis notas.'
    expect(parseVoiceFeedback(transcript)).toEqual({
      rating: 'bad', reasonCode: 'should_have_used_tool', comment: transcript,
      expectedBehavior: 'consultar mis notas en BookShell',
    })
  })

  it('accepts explicit praise but not an isolated thanks', () => {
    expect(parseVoiceFeedback('buena respuesta Jarvis')).toEqual({ rating: 'good' })
    expect(parseVoiceFeedback('gracias')).toBeNull()
  })

  it('only requests a retry when the user gives an explicit new command', () => {
    expect(parseVoiceFeedback('Eso está mal. Busca ahora en BookShell y respóndeme otra vez.')?.followUpMessage)
      .toBe('Busca en BookShell')
    expect(parseVoiceFeedback('Eso está mal, deberías haber mirado BookShell.')?.followUpMessage).toBeUndefined()
  })
})
