// The words the layouts put around the numbers in site-data.json: a recorded run as log lines, the six steps of
// How it works, and the formatting. Checked on the real recorded runs.
import { describe, expect, it } from 'vitest'
import { amount, billTitle, drafted, howSteps, logLines, money, runOf, SITE, toolCount } from './site'

describe('the site words', () => {
  it('names a recorded run by its bill', () => {
    expect(billTitle(runOf('03'))).toBe('Packaging Supplier PKG-20817')
    expect(() => runOf('99')).toThrow(/no recorded run/)
  })

  it('writes a problem bill\'s run as log lines: read, what was found, each lookup, the draft, the pause', () => {
    const lines = logLines(runOf('03'))
    expect(lines.map((l) => l.k)).toEqual(['read', 'check', 'lookup', 'lookup', 'lookup', 'draft', 'pause'])
    expect(lines[1].d).toBe('charged more than the purchase order price ($200.00)')
    expect(lines.slice(2, 5).map((l) => l.d)).toEqual(['the purchase order', 'what was delivered', 'the vendor record'])
    expect(toolCount(runOf('03'))).toBe(3)
    expect(drafted(runOf('03'))).toBe(true)
  })

  it('writes a clean bill as read, passed and waiting for one click', () => {
    const lines = logLines(runOf('09'))
    expect(lines[1]).toEqual({ k: 'check', d: 'every check passed' })
    expect(lines.some((l) => l.k === 'account')).toBe(true)
    expect(lines.at(-1)!.d).toMatch(/one click/)
  })

  it('takes the six steps\' numbers from the data', () => {
    const steps = howSteps()
    expect(steps).toHaveLength(6)
    expect(steps[1].title).toBe(`${SITE.model.name} reads it`)
    expect(steps[2].text).toContain(`${SITE.checks} checks`)
  })

  it('formats money', () => {
    expect(money(0.0991)).toBe('$0.0991')
    expect(amount('2100.00')).toBe('$2,100.00')
  })
})
