export interface VoiceFeedback {
  rating: 'good' | 'bad'
  reasonCode?: 'should_have_used_tool' | 'wrong_tool' | 'action_not_executed' | 'ignored_context' | 'incorrect_information'
  comment?: string
  expectedBehavior?: string
  followUpMessage?: string
}

const normalize = (value: string) => value.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLocaleLowerCase()

function expectedBehavior(transcript: string): string | undefined {
  const match = transcript.match(/(?:deberías haber|deberias haber|tendrías que haber|tendrias que haber|lo correcto sería|lo correcto seria|la respuesta correcta (?:es|sería|seria))\s+([^.!?]+)/i)
  if (!match) return undefined
  let expected = match[1].trim()
  expected = expected
    .replace(/^consultado\b/i, 'consultar')
    .replace(/^mirado\b/i, 'mirar')
    .replace(/^buscado\b/i, 'buscar')
    .replace(/^usado\b/i, 'usar')
    .replace(/^respondido\b/i, 'responder')
  if (/bookshell/i.test(transcript) && !/bookshell/i.test(expected)) expected += ' en BookShell'
  return expected
}

export function parseVoiceFeedback(transcript: string): VoiceFeedback | null {
  const text = normalize(transcript).replace(/\s+/g, ' ').trim()
  const positive = /\b(buena respuesta(?: jarvis)?|perfecto jarvis(?: eso era)?|bien hecho jarvis|esa respuesta esta bien)\b/.test(text)
  if (positive) return { rating: 'good' }

  const negative = /\b(respuesta incorrecta(?: jarvis)?|eso esta mal|mala respuesta(?: jarvis)?|no has (?:buscado|consultado)|deberias haber|tendrias que haber|herramienta equivocada|no (?:hiciste|ejecutaste)|ignoraste (?:lo anterior|el contexto)|la respuesta correcta (?:es|seria)|lo correcto seria)\b/.test(text)
  if (!negative) return null
  const reasonCode = /no has (?:buscado|consultado)|deberias haber (?:usado|consultado|mirado|buscado)|bookshell|mis notas|la api/.test(text)
    ? 'should_have_used_tool'
    : /herramienta equivocada/.test(text)
      ? 'wrong_tool'
      : /no (?:hiciste|ejecutaste)/.test(text)
        ? 'action_not_executed'
        : /ignoraste (?:lo anterior|el contexto)/.test(text)
          ? 'ignored_context'
          : 'incorrect_information'
  const followUp = transcript.match(/\b(busca|consulta|mira)\s+ahora\s+(.+?)(?:\s+y\s+respóndeme\s+otra\s+vez)?[.!?]*$/i)
  return {
    rating: 'bad',
    reasonCode,
    comment: transcript.trim(),
    expectedBehavior: expectedBehavior(transcript),
    followUpMessage: followUp ? `${followUp[1]} ${followUp[2].trim()}` : undefined,
  }
}
