// Usage events and Microsoft Clarity, the same pattern as the rag.irs and recall-desk demos. Events go with
// sendBeacon to EVENTS_URL, which keeps only event types and fields of a fixed shape and adds what it knows about
// the request (place, network, browser).
//   view          one per page load: the look, the link code, the referrer's host, size, setup, visitor id
//   studio_*      Studio open and picks             tab       a desk tab (bills, audit trail, how it works)
//   bill          a bill opened from the queue      decide    approve, hold, reject or the suggested step, and how it went
//   tour          the walkthrough and the map tour  audit     verify, or edit a row behind the app's back
//   example       a recorded run on the map, an eval run opened
//   link          a link out (GitHub, ...)          copy      text copied, where and how long
//   section       seconds each part of the page was in view
//   error         a script error (5 at most)        perf      TTFB, FCP, LCP, CLS, load
//   leave         furthest point read, seconds in view
// On only on the live site: not in the dev server or a local preview (so the browser tests send nothing), not under
// Global Privacy Control, and not in this browser after ?track=off (until ?track=on). Then no events, no visitor id
// and no Clarity. A ?src=<code> on the link is kept for the visit in sessionStorage. The reason typed for a decision
// is never sent, and it is masked in Clarity's recordings (data-clarity-mask in InvoiceView.tsx).
//
// What a click means comes from data attributes on the buttons (data-bill, data-tab, data-tour, data-audit, data-ex,
// data-eval, and the Studio's data-o/-p/-f), read by one listener. The helpers above startTracking are pure and
// tested in track.test.ts.

import type { Choice } from './studio/choice.ts'

const HOST = 'ledger-desk.mniznik.com'
const EVENTS_URL = 'https://events.mniznik.com/api/event'
const CLARITY = 'zh3fb5ng9s' // the Clarity project id; empty: no Clarity
const OFF = 'ledger-desk-no-track', SRC = 'ledger-desk-src', VID = 'ledger-desk-vid'

/** What a link out points at ("github", "linkedin", "rag", "recall", or the host); "" for this page. */
export function linkKind(href: string, here: string): string {
  let host: string
  try {
    host = new URL(href).hostname
  } catch {
    return ''
  }
  if (!host || host === here) return ''
  if (host === 'github.com' || host.endsWith('.github.com')) return 'github'
  if (host.endsWith('linkedin.com')) return 'linkedin'
  if (host === 'rag.irs.mniznik.com') return 'rag'
  if (host === 'recall-desk.mniznik.com') return 'recall'
  return host.slice(0, 40)
}

/** How a decision went, from the API's answer: through, refused by the desk's rules (who may approve what, a
 *  missing reason, already decided), or failed. No status: it went through. */
export function decisionResult(status: number | undefined): 'done' | 'refused' | 'failed' {
  if (status === undefined) return 'done'
  return [400, 403, 409, 422].includes(status) ? 'refused' : 'failed'
}

export function trackingOff(s: { host: string; dev: boolean; gpc: boolean; optedOut: boolean }): boolean {
  return s.host !== HOST || s.dev || s.gpc || s.optedOut
}

// ---------- in the browser ----------

type Send = (t: string, fields: Record<string, unknown>) => void
let send: Send | null = null // set by startTracking when tracking is on
const clarity = (...a: unknown[]) => {
  try {
    ;(window as unknown as { clarity?: (...x: unknown[]) => void }).clarity?.(...a)
  } catch {
    /* never in the way */
  }
}

/** A decision on a bill (InvoiceView.tsx): which button, and the API's status when it did not go through. */
export function trackDecision(kind: 'approve' | 'hold' | 'reject' | 'suggested', status: number | undefined) {
  if (!send) return
  const value = decisionResult(status)
  send('decide', { kind, value, where: 'bill' })
  clarity('event', `decision_${value}`)
}

type Options = { host?: string; beacon?: (body: string) => boolean }

/** Starts the events and Clarity for this page load, once the layout has rendered (main.tsx). The options are for
 *  tests: the host the page is on, and what sends a beacon. */
export function startTracking(choice: Choice, opts: Options = {}) {
  const q = new URLSearchParams(location.search)
  const store = <T,>(s: () => Storage, f: (s: Storage) => T): T | null => {
    try {
      return f(s())
    } catch {
      return null // storage can be blocked
    }
  }
  if (q.get('track') === 'off') store(() => localStorage, (s) => s.setItem(OFF, '1'))
  if (q.get('track') === 'on') store(() => localStorage, (s) => s.removeItem(OFF))
  const off = trackingOff({
    host: opts.host ?? location.hostname,
    dev: import.meta.env?.DEV === true && !opts.host,
    gpc: (navigator as Navigator & { globalPrivacyControl?: boolean }).globalPrivacyControl === true,
    optedOut: store(() => localStorage, (s) => s.getItem(OFF)) === '1',
  })
  if (off) return

  const rand = (n: number) => {
    let s = ''
    while (s.length < n) s += Math.random().toString(36).slice(2)
    return s.slice(0, n)
  }
  let src = (q.get('src') || '').toLowerCase()
  if (!/^[a-z0-9-]{1,40}$/.test(src)) src = ''
  if (src) store(() => sessionStorage, (s) => s.setItem(SRC, src))
  else src = store(() => sessionStorage, (s) => s.getItem(SRC)) || ''
  let vid = store(() => localStorage, (s) => s.getItem(VID)) || ''
  if (!/^[a-z0-9]{12}$/.test(vid)) {
    vid = rand(12)
    store(() => localStorage, (s) => s.setItem(VID, vid))
  }
  const pv = rand(8) // this page load only
  const ctx = { layout: choice.option, palette: choice.palette, font: choice.font, how: choice.source, src, pv, vid }

  const beacon = opts.beacon ?? ((body: string) => navigator.sendBeacon(EVENTS_URL, body))
  send = (t, fields) => {
    const body = JSON.stringify({ t, ...ctx, ...fields })
    try {
      if (!beacon(body)) fetch(EVENTS_URL, { method: 'POST', body, keepalive: true, mode: 'no-cors' }).catch(() => {})
    } catch {
      /* never in the way */
    }
  }
  const emit = send

  // ---------- Microsoft Clarity: recordings and heatmaps, tagged so a recording can be matched to the events ----------
  if (CLARITY && !document.getElementById('clarity-script')) {
    // Microsoft's loader, as in the @microsoft/clarity package (src/utils.js): calls queue until the tag loads
    const w = window as unknown as { clarity?: ((...a: unknown[]) => void) & { q?: IArguments[] } }
    w.clarity =
      w.clarity ||
      function () {
        // eslint-disable-next-line prefer-rest-params
        ;(w.clarity!.q = w.clarity!.q || []).push(arguments)
      }
    const t = document.createElement('script')
    t.async = true
    t.src = 'https://www.clarity.ms/tag/' + CLARITY
    t.id = 'clarity-script'
    document.head.appendChild(t)
    clarity('identify', vid, undefined, pv)
    clarity('set', 'layout', choice.option)
    clarity('set', 'vid', vid)
    clarity('set', 'pv', pv)
    if (src) {
      clarity('set', 'src', src)
      clarity('set', 'app_link', 'yes')
      clarity('upgrade', 'application link')
    }
  }

  // ---------- the view ----------
  const refHost = (() => {
    try {
      const h = new URL(document.referrer).hostname
      return h && h !== location.hostname ? h : ''
    } catch {
      return ''
    }
  })()
  const size = innerWidth < 700 ? 'phone' : innerWidth < 1100 ? 'tablet' : 'desktop'
  const mq = (m: string) => matchMedia(m).matches
  const conn = (navigator as Navigator & { connection?: { effectiveType?: string } }).connection
  const setup = [
    navigator.language || '',
    (() => {
      try {
        return Intl.DateTimeFormat().resolvedOptions().timeZone || ''
      } catch {
        return ''
      }
    })(),
    `${screen.width}x${screen.height}`,
    String(Math.round((devicePixelRatio || 1) * 100) / 100),
    mq('(prefers-color-scheme: dark)') ? 'dark' : 'light',
    mq('(prefers-reduced-motion: reduce)') ? 'reduce' : 'no-pref',
    conn?.effectiveType || '',
  ]
    .map((s) => String(s).replace(/[^A-Za-z0-9_./+:-]/g, ''))
    .join('|')
  emit('view', { ref: refHost, size, setup })

  // where on the page something happened, innermost first
  const where = (el: Element) =>
    el.closest('.trace') ? 'trace'
      : el.closest('.invoice') ? 'bill'
      : el.closest('.audit') ? 'audit'
      : el.closest('.evals') ? 'evals'
      : el.closest('#built, .wf') ? 'built'
      : el.closest('#map, .sm-sec') ? 'map'
      : el.closest('#how, .howbar') ? 'how'
      : el.closest('#desk, .desk, .desk-stage') ? 'desk'
      : el.closest('nav') ? 'nav'
      : 'page'

  // ---------- clicks ----------
  document.addEventListener(
    'click',
    (e) => {
      const el = e.target instanceof Element ? e.target : null
      if (!el) return
      const sp = el.closest<HTMLElement>('.sp-btn, .sp-lay, .sp-pal, .sp-font, .sp-reset')
      if (sp) {
        if (sp.matches('.sp-btn')) return emit('studio_open', {})
        if (sp.matches('.sp-reset')) return emit('studio_pick', { kind: 'reset' })
        const [kind, value] = sp.matches('.sp-lay') ? ['layout', sp.dataset.o] : sp.matches('.sp-pal') ? ['palette', sp.dataset.p] : ['font', sp.dataset.f]
        return emit('studio_pick', { kind, value })
      }
      const d = el.closest<HTMLElement>('[data-bill], [data-tab], [data-tour], [data-audit], [data-ex], [data-eval]')
      if (d) {
        const a = d.dataset
        if (a.bill) {
          clarity('event', 'bill_opened')
          return emit('bill', { value: a.bill, where: where(d) })
        }
        if (a.tab) return emit('tab', { value: a.tab })
        if (a.tour) {
          if (a.tour === 'start' || a.tour === 'finish') clarity('event', `tour_${a.tour}`)
          return emit('tour', { kind: a.tour, value: a.step || '' })
        }
        if (a.audit) {
          clarity('event', `audit_${a.audit}`)
          return emit('audit', { kind: a.audit, where: where(d) })
        }
        if (a.ex) return emit('example', { kind: 'recorded', value: a.ex, where: where(d) })
        if (a.eval) return emit('example', { kind: 'eval', value: a.eval, where: where(d) })
      }
      const link = el.closest<HTMLAnchorElement>('a[href]')
      if (link) {
        const kind = linkKind(link.href, location.hostname)
        if (!kind) return
        if (kind === 'github' || kind === 'linkedin') clarity('event', `link_${kind}`)
        emit('link', { value: kind, where: where(link) })
      }
    },
    true, // capture: a Studio pick reloads the page from its own handler, so count it first
  )

  // ---------- copying ----------
  document.addEventListener('copy', () => {
    const sel = getSelection(), n = sel ? String(sel).length : 0
    const node = sel?.anchorNode ? (sel.anchorNode.nodeType === 1 ? (sel.anchorNode as Element) : sel.anchorNode.parentElement) : null
    if (n) {
      clarity('event', 'copied_text')
      emit('copy', { n, where: node ? where(node) : 'page' })
    }
  })

  // ---------- script errors (5 per page at most) ----------
  let errors = 0
  const err = (message: unknown, file: string) => {
    if (errors++ >= 5) return
    emit('error', { text: String(message || '').slice(0, 200), value: String(file || '').split(/[/?#]/).filter(Boolean).pop() || '' })
  }
  addEventListener('error', (e) => err(e.message, e.filename))
  addEventListener('unhandledrejection', (e) => err(e.reason?.message ?? String(e.reason), ''))

  // ---------- page speed ----------
  const perf = { ttfb: 0, fcp: 0, lcp: 0, cls: 0, load: 0 }
  const watch = (type: string, f: (e: PerformanceEntry & { value?: number; hadRecentInput?: boolean }) => void) => {
    try {
      new PerformanceObserver((l) => l.getEntries().forEach(f)).observe({ type, buffered: true })
    } catch {
      /* not supported */
    }
  }
  watch('paint', (e) => {
    if (e.name === 'first-contentful-paint') perf.fcp = e.startTime
  })
  watch('largest-contentful-paint', (e) => {
    perf.lcp = e.startTime
  })
  watch('layout-shift', (e) => {
    if (!e.hadRecentInput) perf.cls += e.value ?? 0
  })
  const nav = () => {
    const n = performance.getEntriesByType?.('navigation')[0] as PerformanceNavigationTiming | undefined
    if (n) {
      perf.ttfb = n.responseStart
      perf.load = n.loadEventEnd
    }
  }

  // ---------- sections: seconds each part of the page was in view ----------
  const secs = new Map<string, number>(), since = new Map<string, number>(), sentSecs = new Map<string, number>()
  const nameOf = (el: Element) => el.id || el.tagName.toLowerCase()
  const tick = (name: string, on: boolean) => {
    const now = Date.now()
    if (since.has(name)) {
      secs.set(name, (secs.get(name) || 0) + now - since.get(name)!)
      since.delete(name)
    }
    if (on && document.visibilityState === 'visible') since.set(name, now)
  }
  let io: IntersectionObserver | null = null
  const parts = () => [...document.querySelectorAll('section[id], figure[id], main > h2[id], #desk, footer')]
  const observe = () =>
    parts().forEach((el) => {
      io!.unobserve(el)
      io!.observe(el) // observe() reports what is in view now
    })
  try {
    io = new IntersectionObserver(
      (entries) =>
        entries.forEach((e) => {
          const h = Math.min(e.boundingClientRect.height, innerHeight)
          tick(nameOf(e.target), e.isIntersecting && e.intersectionRect.height >= h * 0.25)
        }),
      { threshold: [0, 0.1, 0.25, 0.5, 0.75, 1] },
    )
    observe()
    setTimeout(observe, 1500) // parts a layout renders a moment later
  } catch {
    io = null // no IntersectionObserver
  }

  // ---------- leaving: once each time the page is hidden ----------
  let maxScroll = 0, shown = 0, shownSince = document.visibilityState === 'visible' ? Date.now() : 0, sent = false, perfSent = false
  const read = () => {
    const h = document.documentElement.scrollHeight
    maxScroll = Math.max(maxScroll, h ? Math.min(100, ((scrollY + innerHeight) / h) * 100) : 0)
  }
  addEventListener('scroll', read, { passive: true })
  const leave = () => {
    if (sent) return
    sent = true
    read()
    if (shownSince) {
      shown += Date.now() - shownSince
      shownSince = 0
    }
    ;[...since.keys()].forEach((name) => tick(name, false))
    for (const [name, ms] of secs) {
      const s = Math.round(ms / 1000) - (sentSecs.get(name) || 0)
      if (s > 0) {
        sentSecs.set(name, (sentSecs.get(name) || 0) + s)
        emit('section', { kind: name, secs: s })
      }
    }
    if (!perfSent) {
      perfSent = true
      nav()
      emit('perf', perf)
    }
    emit('leave', { scroll: Math.round(maxScroll), secs: Math.round(shown / 1000) })
  }
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') leave()
    else {
      shownSince = Date.now()
      sent = false
      if (io) observe()
    }
  })
  addEventListener('pagehide', leave)
}
