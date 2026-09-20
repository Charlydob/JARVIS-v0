import type { UserLocation } from './api/client'

const LOCATION_MAX_AGE_MS = 15 * 60 * 1000

type CachedLocation = UserLocation & { capturedAt: number }
type LocationPermission = 'granted' | 'denied' | 'timeout' | 'unavailable' | 'unknown'

let cachedLocation: CachedLocation | undefined

export class DeviceLocationError extends Error {
  constructor(public readonly code: 'denied' | 'timeout' | 'unavailable') {
    super(code === 'denied'
      ? 'Necesito permiso de ubicación para responder a eso, señor.'
      : 'No he podido obtener la ubicación ahora mismo. Puede volver a intentarlo, señor.')
  }
}

export function requiresFreshLocation(message: string): boolean {
  const normalized = message.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLocaleLowerCase()
  return /\b(tiempo|clima|lluv\w*|temperatura|pronostico|prevision|donde estoy|donde estamos|ubicacion|localizacion|cerca de mi|por aqui)\b/.test(normalized)
}

function logLocation(source: 'device' | 'cache', ageMs: number, permission: LocationPermission, refresh: boolean) {
  console.info('[JARVIS location]', {
    location_source: source,
    location_age_s: Math.max(0, Math.round(ageMs / 1000)),
    location_permission: permission,
    location_refresh: refresh,
  })
}

export async function getFreshLocation(
  geolocation: Geolocation | undefined = navigator.geolocation,
  now: () => number = Date.now,
): Promise<UserLocation> {
  const currentTime = now()
  if (cachedLocation && currentTime - cachedLocation.capturedAt <= LOCATION_MAX_AGE_MS) {
    logLocation('cache', currentTime - cachedLocation.capturedAt, 'granted', false)
    return { latitude: cachedLocation.latitude, longitude: cachedLocation.longitude }
  }
  if (!geolocation) {
    logLocation('device', 0, 'unavailable', true)
    throw new DeviceLocationError('unavailable')
  }
  return await new Promise<UserLocation>((resolve, reject) => {
    geolocation.getCurrentPosition(
      ({ coords }) => {
        cachedLocation = { latitude: coords.latitude, longitude: coords.longitude, capturedAt: now() }
        logLocation('device', 0, 'granted', true)
        resolve({ latitude: coords.latitude, longitude: coords.longitude })
      },
      (error) => {
        const code = error.code === error.PERMISSION_DENIED
          ? 'denied' : error.code === error.TIMEOUT ? 'timeout' : 'unavailable'
        logLocation('device', cachedLocation ? currentTime - cachedLocation.capturedAt : 0, code, true)
        reject(new DeviceLocationError(code))
      },
      { enableHighAccuracy: false, maximumAge: LOCATION_MAX_AGE_MS, timeout: 8000 },
    )
  })
}

export function resetLocationCacheForTests() {
  cachedLocation = undefined
}
