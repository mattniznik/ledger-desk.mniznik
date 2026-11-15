import { describe, expect, it } from 'vitest'
import { fieldModel, howSteps, runOf, SITE, walkOf, type FieldCase } from '../site'
import { markSizes } from './field'

// The animated How it works draws only what the data holds: one dot per bill the eval read, with that bill's real
// outcome, and one recorded run's real steps. These pin the data-to-picture mapping.

const c = (id: string, document: string, status: string, exact = true, safe = true): FieldCase => ({ id, document, status, exact, safe })

describe('the dot field', () => {
  it('has one mark per eval bill, with its real outcome', () => {
    const f = fieldModel(SITE.field.cases)
    expect([f.n, f.photos, f.flagged, f.clean, f.exact, f.safe]).toEqual([50, 8, 31, 19, 49, 50])
    expect(f.marks).toHaveLength(50)
    expect(f.marks.filter((m) => m.flagged)).toHaveLength(31)
    expect(f.marks.filter((m) => m.photo)).toHaveLength(8)
    expect(f.marks.filter((m) => !m.exact)).toHaveLength(1)
  })

  it('writes its captions from the counts', () => {
    const f = fieldModel([c('a', 'photo', 'exception'), c('b', 'pdf', 'ready', false)])
    expect(f.captions).toHaveLength(6)
    expect(f.captions[0]).toBe('2 bills from the eval: 1 PDF and 1 phone photo')
    expect(f.captions[2]).toBe('Code checks them: 1 has a problem, 1 is clean')
    expect(f.captions[5]).toContain('1 of 2 ended exactly as their answer key says')
    expect(f.captions[5]).toContain('2 of 2 booked nothing without a person')
  })
})

describe('the marks', () => {
  it('a lit mark always fits inside its own cell', () => {
    for (let pitch = 5; pitch <= 24; pitch++) {
      const s = markSizes(pitch)
      expect(2 * s.lit).toBeLessThanOrEqual(pitch)
      expect(2 * s.pulse).toBeLessThanOrEqual(pitch)
      expect(s.square).toBeLessThanOrEqual(pitch)
    }
  })
})

describe('one recorded run, as the six steps', () => {
  it('the overcharge: what was read, the flag, its three lookups and the draft, the next step, the cost', () => {
    const w = walkOf(runOf('03'))
    expect(w.map((s) => s.kind)).toEqual(['bill', 'read', 'checks', 'lookups', 'decide', 'cost'])
    const read = w[1], checks = w[2], look = w[3], decide = w[4], cost = w[5]
    if (read.kind !== 'read' || checks.kind !== 'checks' || look.kind !== 'lookups' || decide.kind !== 'decide' || cost.kind !== 'cost') throw new Error('kinds')
    expect([read.ok, read.of]).toEqual([6, 6])
    expect(checks.flags.map((f) => f.code)).toEqual(['PRICE_VARIANCE'])
    expect(look.lookups.map((l) => l.tool)).toEqual(['get_purchase_order', 'get_receipts', 'get_vendor'])
    expect(look.drafted).toBe(true)
    expect(decide.next).toBe('Hold for a corrected bill')
    expect([cost.calls, cost.lookups, cost.maxLookups]).toEqual([4, 3, SITE.policies.max_lookups])
  })

  it('a clean bill: no lookups, and one click from a person', () => {
    const w = walkOf(runOf('09'))
    const look = w[3], decide = w[4]
    if (look.kind !== 'lookups' || decide.kind !== 'decide') throw new Error('kinds')
    expect(look.lookups).toEqual([])
    expect(decide.next).toBe('Approve: every check passed')
  })

  it('each of the six steps has a short label for the figures', () => {
    expect(howSteps().every((s) => s.sub.length > 0)).toBe(true)
  })
})
