export type SpeechSegment = {
  text: string
  pauseAfterMs: number
  boundary: 'sentence' | 'paragraph' | 'continuation'
}

function segment(text: string, boundary: SpeechSegment['boundary'], whitespace = ''): SpeechSegment {
  return {
    text: text.trim(),
    boundary,
    // Edge voices already include natural prosody. These short pauses only
    // preserve paragraph structure without adding a second audible gap.
    pauseAfterMs: boundary === 'paragraph' || /\n\s*\n/.test(whitespace) ? 120 : boundary === 'sentence' ? 15 : 0,
  }
}

export function takeSpeechSegments(value: string, flush = false): { segments: SpeechSegment[]; remainder: string } {
  const segments: SpeechSegment[] = []
  let remainder = value
  const sentence = /[.!?…]+["'»”)]*(\s+)/
  while (true) {
    const match = sentence.exec(remainder)
    if (!match) break
    const end = match.index + match[0].length
    segments.push(segment(remainder.slice(0, end), /\n\s*\n/.test(match[1]) ? 'paragraph' : 'sentence', match[1]))
    remainder = remainder.slice(end)
  }
  while (!flush && remainder.length > 240) {
    const window = remainder.slice(0, 240)
    const punctuation = Math.max(window.lastIndexOf(','), window.lastIndexOf(';'), window.lastIndexOf(':'))
    const space = window.lastIndexOf(' ')
    const cut = punctuation >= 120 ? punctuation + 1 : space >= 120 ? space : 240
    segments.push(segment(remainder.slice(0, cut), 'continuation'))
    remainder = remainder.slice(cut).trimStart()
  }
  if (flush && remainder.trim()) {
    segments.push(segment(remainder, 'continuation'))
    remainder = ''
  }
  return { segments: segments.filter((item) => Boolean(item.text)), remainder }
}
