export function takeSpeechSegments(value: string, flush = false): { segments: string[]; remainder: string } {
  const segments: string[] = []
  let remainder = value
  const sentence = /[.!?…]+["'»”)]*\s+/
  while (true) {
    const match = sentence.exec(remainder)
    if (!match) break
    const end = match.index + match[0].length
    segments.push(remainder.slice(0, end).trim())
    remainder = remainder.slice(end)
  }
  while (!flush && remainder.length > 240) {
    const window = remainder.slice(0, 240)
    const punctuation = Math.max(window.lastIndexOf(','), window.lastIndexOf(';'), window.lastIndexOf(':'))
    const space = window.lastIndexOf(' ')
    const cut = punctuation >= 120 ? punctuation + 1 : space >= 120 ? space : 240
    segments.push(remainder.slice(0, cut).trim())
    remainder = remainder.slice(cut).trimStart()
  }
  if (flush && remainder.trim()) {
    segments.push(remainder.trim())
    remainder = ''
  }
  return { segments: segments.filter(Boolean), remainder }
}
