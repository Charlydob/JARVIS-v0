export type SpeechInterrupt =
  | { kind: 'ignore' }
  | { kind: 'stop' }
  | { kind: 'message'; message: string }

export type VoiceCaptureMode = 'normal' | 'interrupt' | undefined

export function desiredVoiceCaptureMode(paused: boolean, conversationState: string): VoiceCaptureMode {
  if (!paused) return 'normal'
  return conversationState.toUpperCase() === 'SPEAKING' ? 'interrupt' : undefined
}

function normalized(value: string) {
  return value.normalize('NFD').replace(/\p{M}/gu, '').toLocaleLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, ' ').trim()
}

function editDistance(left: string, right: string) {
  const row = Array.from({ length: right.length + 1 }, (_, index) => index)
  for (let leftIndex = 1; leftIndex <= left.length; leftIndex += 1) {
    let diagonal = row[0]
    row[0] = leftIndex
    for (let rightIndex = 1; rightIndex <= right.length; rightIndex += 1) {
      const previous = row[rightIndex]
      row[rightIndex] = Math.min(
        row[rightIndex] + 1,
        row[rightIndex - 1] + 1,
        diagonal + (left[leftIndex - 1] === right[rightIndex - 1] ? 0 : 1),
      )
      diagonal = previous
    }
  }
  return row[right.length]
}

function isJarvisToken(value: string) {
  const token = normalized(value)
  return token === 'jarvis' || editDistance(token, 'jarvis') <= 1
}

function isStopCommand(value: string) {
  const text = normalized(value)
  if (/^(?:calla|callate|corta|para|stop)(?: por favor)?$/.test(text)) return true
  if (/^(?:vale vale|ok ok)$/.test(text)) return true
  const single = text.split(' ')
  return single.length === 1 && ['calla', 'callate', 'corta', 'para', 'stop']
    .some((command) => editDistance(single[0], command) <= 1)
}

export function parseSpeechInterrupt(transcript: string): SpeechInterrupt {
  const trimmed = transcript.trim()
  if (!trimmed) return { kind: 'ignore' }
  const leading = trimmed.match(/^[¿¡,.;:!?—–-]*\s*([\p{L}]+)(?:[\s,.;:!?—–-]+([\s\S]*))?$/u)
  if (leading && isJarvisToken(leading[1])) {
    const remainder = (leading[2] ?? '').trim()
    if (!remainder || isStopCommand(remainder)) return { kind: 'stop' }
    return { kind: 'message', message: remainder }
  }
  return isStopCommand(trimmed) ? { kind: 'stop' } : { kind: 'ignore' }
}
