// The page's usage events: when nothing is sent at all, how a link out and a decision's result are named, and what
// a click on the desk, the walkthrough, the audit trail and the Studio sends. track.ts beacons to a shared endpoint
// that keeps only event types and fields it knows; these tests pin what the page sends.
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import { decisionResult, linkKind, startTracking, trackDecision, trackingOff } from './track'

const HOST = 'ledger-desk.mniznik.com'

describe('tracking is off', () => {
  it('everywhere but the live site, under Global Privacy Control, after ?track=off, and in the dev server', () => {
    const on = { host: HOST, dev: false, gpc: false, optedOut: false }
    expect(trackingOff(on)).toBe(false)
    // a deployed copy on its cloud default address is not the live site either
    for (const host of ['127.0.0.1', 'localhost', 'example-app.azurestaticapps.net', `${HOST}.example.org`]) {
      expect(trackingOff({ ...on, host }), host).toBe(true)
    }
    expect(trackingOff({ ...on, dev: true })).toBe(true)
    expect(trackingOff({ ...on, gpc: true })).toBe(true)
    expect(trackingOff({ ...on, optedOut: true })).toBe(true)
  })
})

describe('names', () => {
  it('a link out is named by where it goes; a link within the page is not a link out', () => {
    expect(linkKind('https://github.com/someone/ledger-desk.mniznik/blob/main/src/ledger_desk/rules.py', HOST)).toBe('github')
    expect(linkKind('https://www.linkedin.com/in/someone', HOST)).toBe('linkedin')
    expect(linkKind('https://rag.irs.mniznik.com/', HOST)).toBe('rag')
    expect(linkKind('https://recall-desk.mniznik.com/', HOST)).toBe('recall')
    expect(linkKind('https://www.afponline.org/publications-data', HOST)).toBe('www.afponline.org')
    expect(linkKind(`https://${HOST}/#how`, HOST)).toBe('')
    expect(linkKind('not a url', HOST)).toBe('')
  })

  it("a decision went through, was refused by the desk's rules, or failed", () => {
    expect(decisionResult(undefined)).toBe('done')
    for (const s of [400, 403, 409, 422]) expect(decisionResult(s), String(s)).toBe('refused')
    for (const s of [0, 404, 500, 502]) expect(decisionResult(s), String(s)).toBe('failed')
  })
})

describe('on the live site', () => {
  const sent: Record<string, unknown>[] = []
  beforeAll(() => {
    // jsdom has no matchMedia; the page reads it for the visitor's colour scheme and motion setting
    vi.stubGlobal('matchMedia', (media: string) => ({ matches: false, media }))
    document.body.innerHTML = `
      <section id="desk">
        <button data-tab="audit">Audit trail</button>
        <button data-bill="REP-3307" aria-label="Review REP-3307">Review</button>
        <button data-tour="start">Walk through a morning</button>
        <button data-tour="step" data-step="2">Next</button>
        <section class="audit"><button data-audit="tamper">Edit a row</button></section>
        <a href="https://github.com/someone/ledger-desk.mniznik">Code</a>
        <a href="#how">How</a>
      </section>
      <div class="sp-panel"><button class="sp-pal" data-p="ledgerBlue">Ledger blue</button></div>`
    startTracking(
      { option: '01', palette: 'goldenHour', font: 'geist', source: 'default' },
      { host: HOST, beacon: (body) => (sent.push(JSON.parse(body)), true) },
    )
  })
  afterAll(() => {
    document.body.innerHTML = ''
    vi.unstubAllGlobals()
  })
  const click = (sel: string) => (document.querySelector(sel) as HTMLElement).click()
  const last = () => sent[sent.length - 1]

  it('one view per page load, with the look and the two random ids, and never a visitor-typed word', () => {
    expect(sent[0]).toMatchObject({ t: 'view', layout: '01', palette: 'goldenHour', font: 'geist', how: 'default' })
    expect(sent[0].pv).toMatch(/^[a-z0-9]{8}$/)
    expect(sent[0].vid).toMatch(/^[a-z0-9]{12}$/)
  })

  it('names what was clicked: a desk tab, a bill, a walkthrough step, an audit check, a Studio pick, a link out', () => {
    click('[data-tab]')
    expect(last()).toMatchObject({ t: 'tab', value: 'audit' })
    click('[data-bill]')
    expect(last()).toMatchObject({ t: 'bill', value: 'REP-3307', where: 'desk' })
    click('[data-tour="start"]')
    expect(last()).toMatchObject({ t: 'tour', kind: 'start' })
    click('[data-tour="step"]')
    expect(last()).toMatchObject({ t: 'tour', kind: 'step', value: '2' })
    click('[data-audit]')
    expect(last()).toMatchObject({ t: 'audit', kind: 'tamper', where: 'audit' })
    click('.sp-pal')
    expect(last()).toMatchObject({ t: 'studio_pick', kind: 'palette', value: 'ledgerBlue' })
    const before = sent.length
    document.querySelector('a[href="#how"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    expect(sent.length, 'a link within the page is not a link out').toBe(before)
    const out = document.querySelector('a[href^="https://github.com"]')!
    out.addEventListener('click', (e) => e.preventDefault()) // jsdom does not navigate
    out.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    expect(last()).toMatchObject({ t: 'link', value: 'github', where: 'desk' })
  })

  it('a decision says which button and how it went, and never carries the typed reason', () => {
    trackDecision('approve', 403)
    expect(last()).toMatchObject({ t: 'decide', kind: 'approve', value: 'refused' })
    trackDecision('suggested', undefined)
    expect(last()).toMatchObject({ t: 'decide', kind: 'suggested', value: 'done' })
    expect(JSON.stringify(sent)).not.toMatch(/reason|text/)
  })
})
