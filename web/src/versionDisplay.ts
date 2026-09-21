export type RuntimeVersion = { version?: string; buildSha?: string }

function compactSha(value?: string): string {
  if (!value || ['unknown', 'development', 'offline'].includes(value)) return value || 'unknown'
  return value.slice(0, 7)
}

function label(prefix: string, runtime: RuntimeVersion): string {
  return `${prefix} v${runtime.version || 'unknown'} · ${compactSha(runtime.buildSha)}`
}

export function versionDisplayLines(web: RuntimeVersion, core?: RuntimeVersion | null): string[] {
  if (core && web.version === core.version && web.buildSha === core.buildSha) {
    return [label('JARVIS', web)]
  }
  if (!core) return [label('WEB', web), 'CORE · desconectado']
  return [label('WEB', web), label('CORE', core)]
}
