import { describe, expect, it } from 'vitest'
import { nowIso, todayIn } from './clock'

describe('todayIn', () => {
  it('resolves the civil date in the given zone, not in UTC', () => {
    // 03:00 UTC on the 9th is still 22:00 on the 8th at UTC-5. Getting this
    // wrong shifts "today" — and with it overdue, streak and pace.
    expect(todayIn('America/New_York', new Date('2030-01-09T03:00:00Z'))).toBe('2030-01-08')
    expect(todayIn('UTC', new Date('2030-01-09T03:00:00Z'))).toBe('2030-01-09')
  })

  it('formats as YYYY-MM-DD, zero padded', () => {
    expect(todayIn('UTC', new Date('2030-02-03T17:00:00Z'))).toBe('2030-02-03')
  })
})

describe('nowIso', () => {
  it('hands the engine an instant it can freeze a completion on', () => {
    expect(nowIso(new Date('2030-02-03T17:00:00Z'))).toBe('2030-02-03T17:00:00.000Z')
  })
})
