export type JarvisState = 'sleeping' | 'idle' | 'listening' | 'thinking' | 'speaking' | 'error'

export type JarvisEvent =
  | { type: 'WAKE' }
  | { type: 'SLEEP' }
  | { type: 'START_LISTENING' }
  | { type: 'SUBMIT' }
  | { type: 'RESPONSE' }
  | { type: 'SPEECH_END' }
  | { type: 'FAIL' }
  | { type: 'RESET' }

const transitions: Record<JarvisState, Partial<Record<JarvisEvent['type'], JarvisState>>> = {
  sleeping: { WAKE: 'idle', START_LISTENING: 'listening', FAIL: 'error' },
  idle: { SLEEP: 'sleeping', START_LISTENING: 'listening', SUBMIT: 'thinking', FAIL: 'error' },
  listening: { SLEEP: 'sleeping', SUBMIT: 'thinking', FAIL: 'error' },
  thinking: { SLEEP: 'sleeping', RESPONSE: 'speaking', FAIL: 'error' },
  speaking: { SLEEP: 'sleeping', SPEECH_END: 'idle', START_LISTENING: 'listening', FAIL: 'error' },
  error: { RESET: 'idle', SLEEP: 'sleeping' }
}

export function transition(state: JarvisState, event: JarvisEvent): JarvisState {
  return transitions[state][event.type] ?? state
}

export const stateLabels: Record<JarvisState, string> = {
  sleeping: 'En reposo', idle: 'Disponible', listening: 'Escuchando',
  thinking: 'Pensando', speaking: 'Hablando', error: 'Sin conexión'
}
