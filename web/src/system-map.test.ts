import { describe, expect, it } from 'vitest'
import type { Run } from './api'
import { runOf, SITE } from './site'
import { eventsFromRecorded, eventsFromRun, mapBeats, mapGraph, mapState, tourFor, TOUR_SAMPLE } from './system-map'

// The system map's pure part: the graph of the bill workflow, and which piece each step of a run lights, with a
// caption. Every number in a caption comes from the run or from site-data.json.

const ids = () => mapGraph().nodes.map((n) => n.id)

describe('the graph', () => {
  it('has every piece of the workflow, and every edge joins two of them', () => {
    const g = mapGraph()
    for (const id of ['bill', 'read', 'sources', 'checks', 'account', 'agent', 'playbook', 'person', 'sign', 'erp', 'qbo', 'audit', 'booked', 'held', 'rejected'])
      expect(ids()).toContain(id)
    for (const t of ['get_vendor', 'get_purchase_order', 'get_receipts', 'get_bills', 'draft_vendor_email']) expect(ids()).toContain(`tool:${t}`)
    for (const e of g.edges) {
      expect(ids()).toContain(e.from)
      expect(ids()).toContain(e.to)
    }
  })

  it('takes its numbers from the site data', () => {
    const byId = Object.fromEntries(mapGraph().nodes.map((n) => [n.id, n]))
    expect(byId.checks.label).toBe(`${SITE.checks} checks`)
    expect(byId.agent.sub).toContain(`${SITE.policies.max_lookups} lookups`)
    expect(byId.person.sub).toContain('$5,000')
    expect(byId.read.label).toContain(SITE.model.name)
  })

  it('has plain words: no em dashes, no exclamation marks', () => {
    for (const n of mapGraph().nodes) expect(`${n.label} ${n.sub} ${n.info}`).not.toMatch(/[—!]/)
  })
})

describe('a recorded run on the map', () => {
  it('turns the overcharge into its steps, in order', () => {
    expect(eventsFromRecorded(runOf('03')).map((e) => e.type)).toEqual(['bill', 'read', 'sources', 'checks', 'lookup', 'lookup', 'lookup', 'lookup', 'next', 'pause', 'done'])
  })

  it('lights each piece in turn, with what came back written on the tool', () => {
    const beats = mapBeats(eventsFromRecorded(runOf('03')))
    expect(beats[0].node).toBe('bill')
    const checks = beats.find((b) => b.node === 'checks')!
    expect(checks.tone).toBe('bad')
    expect(checks.caption).toContain('$200.00')
    const po = beats.find((b) => b.node === 'tool:get_purchase_order')!
    expect(po.edge).toBe('agent>tool:get_purchase_order')
    expect(po.note).toEqual({ node: 'tool:get_purchase_order', text: 'PO-1124: 1 line, 5,000 Hot cup, 12 oz at $0.38' })
    expect(beats.find((b) => b.node === 'playbook')!.caption).toContain('Hold for a corrected bill')
    const last = beats.at(-1)!
    expect(last.caption).toContain(`$${runOf('03').cost_usd.toFixed(4)}`)
    expect(last.caption).toContain(`${runOf('03').seconds.toFixed(1)} s`)
  })

  it('sends a clean bill with no purchase order past the agent, through the account check, to one click', () => {
    const events = eventsFromRecorded(runOf('09'))
    expect(events.map((e) => e.type)).toEqual(['bill', 'read', 'sources', 'checks', 'account', 'pause', 'done'])
    const beats = mapBeats(events)
    expect(beats.find((b) => b.node === 'checks')!.tone).toBe('ok')
    expect(beats.some((b) => b.node === 'agent')).toBe(false)
    expect(beats.find((b) => b.node === 'person')!.caption).toContain('one click')
    expect(mapState(beats, beats.length - 1).status.person).toBeUndefined() // one click waiting is not approved yet
  })

  it('lights what has been reached so far', () => {
    const beats = mapBeats(eventsFromRecorded(runOf('03')))
    const st = mapState(beats, 2)
    expect(st.active).toBe(beats[2])
    expect(st.nodes).toEqual(expect.arrayContaining(['bill', 'read']))
    expect(st.nodes).not.toContain('person')
    expect(mapState(beats, beats.length - 1).notes['tool:get_receipts']).toBe('1 delivery: 5,000 received')
    expect(mapState(beats, beats.length - 1).status.person).toBeUndefined() // waiting is not approved
  })

  it('gives the tour a title and a sentence for each step', () => {
    const tour = tourFor(runOf(TOUR_SAMPLE))
    expect(TOUR_SAMPLE).toBe('03')
    expect(tour.length).toBe(mapBeats(eventsFromRecorded(runOf('03'))).length)
    for (const s of tour) expect(s.title.length && s.info.length).toBeTruthy()
  })
})

describe('the run the desk shows', () => {
  const base = {
    run_id: 'r', sample: '08', invoice_ref: 'x', mode: 'replay', model: 'claude-opus-5-5', status: 'exception', paused: true, reason: '', entry_id: null,
    metrics: { model_calls: 3, input_tokens: 0, cache_write_tokens: 0, cache_read_tokens: 0, output_tokens: 0, cost_usd: 0.1 }, seconds: 22.7, due_date: null, mirror: null,
    extraction: { vendor_name: 'Espresso Repair Service', number: 'REP-3307', date: '2026-11-10', total: '860.00', po: null, remit_bank: 'Example Bank', remit_account_last4: '9921', lines: [] },
    source_checks: { number: 'ok', total: 'ok' }, email_draft: null, held: false, next_step: null,
    flags: [{ code: 'BANK_CHANGED', detail: 'remit-to account ending 9921, vendor master ending 4417', amount: null, quantity: null }],
    lookups: [{ tool: 'get_vendor', input: { tax_id: '00-0000005' }, result: 'Espresso Repair Service, Example Bank account ending 4417', ok: true }],
    pause: { invoice_ref: 'x', status: 'exception', approver: 'controller', controller_only: true, total: '860.00', flags: [], explanation: '', account_suggestion: null, proposal: { lines: [] } },
  } as unknown as Run

  it('follows the bill to the person while it waits', () => {
    const beats = mapBeats(eventsFromRun(base))
    expect(beats.at(-1)!.node).toBe('person')
    expect(beats.find((b) => b.node === 'tool:get_vendor')!.note!.text).toContain('4417')
  })

  it('carries on through the signature, the books and QuickBooks once it is approved', () => {
    const posted = { ...base, status: 'posted', paused: false, pause: null, entry_id: 41, mirror: { status: 'mirrored', entity: 'Bill', id: '150', doc_number: 'REP-3307', created: true, total: 860 } } as unknown as Run
    const nodes = mapBeats(eventsFromRun(posted)).map((b) => b.node)
    expect(nodes).toEqual(expect.arrayContaining(['sign', 'erp', 'qbo', 'booked']))
  })

  it('ends on hold or rejected without touching the books', () => {
    const rejected = { ...base, status: 'rejected', paused: false, pause: null } as unknown as Run
    const nodes = mapBeats(eventsFromRun(rejected)).map((b) => b.node)
    expect(nodes).toContain('rejected')
    expect(nodes).not.toContain('erp')
    const held = mapBeats(eventsFromRun({ ...base, held: true })).map((b) => b.node)
    expect(held.at(-1)).toBe('held')
  })
})
