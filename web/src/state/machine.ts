export type JarvisState = 'sleeping' | 'idle' | 'listening' | 'thinking' | 'speaking' | 'muted' | 'error'

export type JarvisEvent =
  | { type: 'CORE_ONLINE' }
  | { type: 'CORE_OFFLINE' }
  | { type: 'MUTE' }
  | { type: 'UNMUTE' }
  | { type: 'START_LISTENING' }
  | { type: 'SUBMIT' }
  | { type: 'RESPONSE' }
  | { type: 'SPEECH_END' }
  | { type: 'EMPTY_AUDIO' }
  | { type: 'FAIL' }
  | { type: 'RESET' }

const activeTransitions: Partial<Record<JarvisEvent['type'], JarvisState>> = {
  CORE_OFFLINE: 'sleeping',
  MUTE: 'muted',
  FAIL: 'error'
}

const transitions: Record<JarvisState, Partial<Record<JarvisEvent['type'], JarvisState>>> = {
  sleeping: { CORE_ONLINE: 'idle', MUTE: 'muted' },
  idle: { ...activeTransitions, START_LISTENING: 'listening', SUBMIT: 'thinking' },
  listening: { ...activeTransitions, SUBMIT: 'thinking' },
  thinking: { ...activeTransitions, RESPONSE: 'speaking', EMPTY_AUDIO: 'listening' },
  speaking: { ...activeTransitions, SPEECH_END: 'listening' },
  muted: { CORE_OFFLINE: 'sleeping', UNMUTE: 'idle' },
  error: { CORE_OFFLINE: 'sleeping', MUTE: 'muted', RESET: 'idle', START_LISTENING: 'listening' }
}

export function transition(state: JarvisState, event: JarvisEvent): JarvisState {
  return transitions[state][event.type] ?? state
}

export const stateLabels: Record<JarvisState, string> = {
  sleeping: 'Core desconectado',
  idle: 'Preparado',
  listening: 'Escuchando',
  thinking: 'Pensando',
  speaking: 'Hablando',
  muted: 'Micrófono silenciado',
  error: 'Necesito atención'
}
