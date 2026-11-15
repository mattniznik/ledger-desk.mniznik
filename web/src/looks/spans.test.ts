import { describe, expect, it } from 'vitest'
import { runOf } from '../site'
import { mapGraph } from '../system-map'
import { spansOf } from './spans'

// The trace waterfall (layout 11) draws one recorded run as steps: each model call with the tokens the API reported,
// the code checks and each tool call, in the order they ran. Only measured shares get a bar.

describe('a recorded run as trace steps', () => {
  it('the overcharge: the reading, the checks, three investigation calls with their tools, the next step, the person', () => {
    const spans = spansOf(runOf('03'))
    expect(spans.map((s) => s.name)).toEqual([
      'bill',
      'model · reads the bill',
      'code · source check',
      'code · checks',
      'model · looks into it',
      'tool · purchase order',
      'tool · deliveries',
      'tool · vendor record',
      'model · looks into it',
      'tool · draft email',
      'model · looks into it',
      'code · next step',
      'a person decides',
    ])
  })

  it('bars only what was measured: the model calls share the run tokens, nothing else gets a bar', () => {
    const r = runOf('03')
    const spans = spansOf(r)
    const model = spans.filter((s) => s.kind === 'model')
    expect(model.reduce((n, s) => n + s.share, 0)).toBeCloseTo(1, 6)
    expect(spans.filter((s) => s.kind !== 'model' && s.kind !== 'root').every((s) => s.share === 0)).toBe(true)
    expect(model[0].value).toBe(`${r.usage[0].tokens.toLocaleString('en-US')} tok`)
  })

  it('flags the checks step when the checks found a problem, and points every step at a piece of the map', () => {
    const ids = new Set(mapGraph().nodes.map((n) => n.id))
    for (const sample of ['03', '08', '09']) for (const s of spansOf(runOf(sample))) expect(ids.has(s.node), `${sample} ${s.name} -> ${s.node}`).toBe(true)
    expect(spansOf(runOf('03')).find((s) => s.name === 'code · checks')!.bad).toBe(true)
    expect(spansOf(runOf('09')).find((s) => s.name === 'code · checks')!.bad).toBe(false)
  })
})
