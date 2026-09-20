import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getFreshLocation, requiresFreshLocation, resetLocationCacheForTests } from './deviceLocation'

describe('device location', () => {
  beforeEach(() => resetLocationCacheForTests())

  it('refreshes once and reuses a position for fifteen minutes', async () => {
    const getCurrentPosition = vi.fn((success: PositionCallback) => success({
      coords: { latitude: 40.4, longitude: -3.7 } as GeolocationCoordinates,
      timestamp: 0,
    } as GeolocationPosition))
    const geolocation = { getCurrentPosition } as unknown as Geolocation
    expect(await getFreshLocation(geolocation, () => 1_000)).toEqual({ latitude: 40.4, longitude: -3.7 })
    expect(await getFreshLocation(geolocation, () => 901_000)).toEqual({ latitude: 40.4, longitude: -3.7 })
    expect(getCurrentPosition).toHaveBeenCalledTimes(1)
  })

  it('reports denied permission and detects requests that need location', async () => {
    const geolocation = { getCurrentPosition: (_ok: PositionCallback, fail: PositionErrorCallback) => fail({ code: 1, PERMISSION_DENIED: 1, POSITION_UNAVAILABLE: 2, TIMEOUT: 3 } as GeolocationPositionError) } as unknown as Geolocation
    await expect(getFreshLocation(geolocation)).rejects.toEqual(expect.objectContaining({ code: 'denied' }))
    expect(requiresFreshLocation('qué tiempo hará mañana donde estoy')).toBe(true)
    expect(requiresFreshLocation('abre la segunda fuente')).toBe(false)
  })
})
