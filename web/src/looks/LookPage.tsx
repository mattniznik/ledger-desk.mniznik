// The five layouts built around the system map (10-14), each with the structure of one design reference: patterns
// are borrowed, nothing is copied (no logo, product name, illustration or copy text from any of them).
//
//   10 canvas    - a workflow-run canvas: the recorded bills in a rail, the map as the canvas, the desk as its panel
//   11 waterfall - an observability trace: one recorded run as a tree of steps with measured bars, a detail panel
//   12 workshop  - a light tabbed sheet: a tab per lookup and one for the checks, beside the map on graph paper
//   13 spec      - a dark spec sheet: a numbered index, the map as Fig. 1 with numbered callouts, the checks as a table
//   14 garage    - friendly status cards; a tap finds the piece on the map
//
// Each keeps everything the other layouts have: the bill desk, the system map with its tour, how it works, the
// measured runs, how it was built, and the footer's disclaimer. Every number comes from site-data.json (site.ts).

import { useEffect, useMemo, useState, type ReactNode } from 'react'

import '../rich/rich.css'
import './looks.css'
import { Desk as BillDesk } from '../Desk.tsx'
import { BeforeAfter } from '../shared/BeforeAfter.tsx'
import { Studio } from '../studio/Studio.tsx'
import type { Cfg, Choice } from '../studio/choice.ts'
import { Built } from '../shared/Built.tsx'
import { SystemMap } from '../shared/SystemMap.tsx'
import { DeskLink, Proof } from '../rich/RichPage.tsx'
import { COMPANY, COST_RANGE, DISCLAIMER, LEDE, SITE, STACK, TESTS } from '../shared/data.ts'
import { useMotion } from '../live.ts'
import { publish, requestTour } from '../map-feed.ts'
import { eventsFromRecorded, lookupInput, mapGraph, toolLabel, TOOLS } from '../system-map.ts'
import { READS, spansOf } from './spans.ts'
import { amount, billTitle, controllerFrom, FLAG_CODES, flagWords, howSteps, money, type RecordedRun } from '../site.ts'

const RUNS = SITE.recorded.runs
const GRAPH = mapGraph()
const HOW = howSteps()
const nodeOf = (id: string) => GRAPH.nodes.find((n) => n.id === id)!
const runTitle = (r: RecordedRun) => `${r.number}: ${r.flags.length ? flagWords(r.flags[0].code) : 'every check passed'}`
const runLine = (r: RecordedRun) => `${r.flags.length ? 'Flagged, waiting for a person' : 'Clean, one click'} · ${r.seconds.toFixed(1)} s · ${money(r.cost_usd)}`
const runTone = (r: RecordedRun) => (r.flags.length ? 'held' : 'ok')

/** Play a recorded run on the map (and say so in its caption). */
const playRun = (r: RecordedRun, from: string) => publish({ id: `${from}-${r.sample}-${Date.now()}`, title: runTitle(r), mode: 'replay', events: eventsFromRecorded(r) })

/** A lookup's first use in the recorded runs: the bill, what was asked and what came back. */
function firstCall(tool: string) {
  for (const r of RUNS) {
    const l = r.lookups.find((x) => x.tool === tool)
    if (l) return { run: r, input: lookupInput(l.input), result: l.result }
  }
  return null
}

/** How many recorded bills a check flagged. */
const flaggedBy = (code: string) => RUNS.filter((r) => r.flags.some((f) => f.code === code)).length

/* ---------------------------------------------------------------- shared frame */

const TourButton = ({ className = 'btn' }: { className?: string }) => (
  <button type="button" className={className} onClick={() => requestTour()}>
    Take the tour
  </button>
)

function Nav({ choice, links, center = false }: { choice: Choice; links: [string, string][]; center?: boolean }) {
  return (
    <nav className={`nav lk-nav${center ? ' lk-center' : ''}`} aria-label="Sections">
      <div className="wrap">
        <span className="brand">
          <i />
          {COMPANY}
        </span>
        <Studio choice={choice} placement="nav" />
        <span className="links">
          {links.map(([h, t]) => (
            <a key={h} href={h}>
              {t}
            </a>
          ))}
        </span>
        <DeskLink className="btn go small" />
      </div>
    </nav>
  )
}

function Foot() {
  return (
    <footer className="foot lk-foot">
      <div className="wrap">
        <div className="grid">
          <div>
            <span className="brand">
              <i />
              {COMPANY}
            </span>
            <p className="muted disclaimer">{DISCLAIMER}</p>
            <div className="stack">
              {STACK.map((s) => (
                <span key={s}>{s}</span>
              ))}
            </div>
          </div>
          <div className="btns end">
            <DeskLink className="btn go" />
            <a className="btn" href="#map">
              The system map
            </a>
          </div>
        </div>
      </div>
    </footer>
  )
}

/** How it works in words: the six steps, numbered, for the layouts whose map needs a text beside it. */
function Steps({ className = '' }: { className?: string }) {
  return (
    <ol className={`lk-steps ${className}`}>
      {HOW.map((h, i) => (
        <li key={h.title}>
          <span className="lk-sn">{String(i + 1).padStart(2, '0')}</span>
          <div>
            <b>{h.title}</b> <span className="lk-sub">{h.sub}</span>
            <p>{h.text}</p>
          </div>
        </li>
      ))}
    </ol>
  )
}

const DeskBox = ({ className = '' }: { className?: string }) => (
  <div className={`desk-stage lk-desk ${className}`}>
    <BillDesk />
  </div>
)

export function LookPage({ cfg, choice }: { cfg: Cfg; choice: Choice }) {
  useEffect(() => document.documentElement.classList.remove('boot'), [])
  switch (cfg.look) {
    case 'waterfall':
      return <Waterfall choice={choice} />
    case 'workshop':
      return <Workshop choice={choice} />
    case 'spec':
      return <Spec choice={choice} />
    case 'garage':
      return <Garage choice={choice} />
    default:
      return <Canvas choice={choice} />
  }
}

type PageProps = { choice: Choice }

/* ---------------------------------------------------------------- 10 · run canvas */

function Canvas({ choice }: PageProps) {
  const [on, setOn] = useState<string | null>(null)
  return (
    <>
      <Nav choice={choice} links={[['#map', 'Canvas'], ['#how', 'How it works'], ['#proof', 'Results'], ['#built', 'How it was built']]} />
      <main>
      <header className="lk-c-head wrap">
        <p className="lk-crumb">
          {COMPANY} <span>/</span> accounts payable <span>/</span> <b>bills</b>
        </p>
        <div className="lk-c-title">
          <h1 className="h1">Watch each bill go through, one piece at a time.</h1>
          <span className="pill nf">Recorded runs, replayed</span>
        </div>
        <p className="lede">{LEDE}</p>
      </header>
      <div className="wrap">
        <BeforeAfter />
      </div>
      <section className="lk-c-shell wrap" id="map">
        <aside className="lk-c-rail" aria-label="Recorded bills">
          <div className="lk-c-railhead">
            <b>Bills</b>
            <span>{SITE.recorded.n} recorded</span>
          </div>
          <ul>
            {RUNS.map((r) => (
              <li key={r.sample}>
                <button
                  type="button"
                  className={`lk-run ${runTone(r)}${on === r.sample ? ' on' : ''}`}
                  aria-pressed={on === r.sample}
                  onClick={() => {
                    setOn(r.sample)
                    playRun(r, 'rail')
                  }}
                >
                  <b>{runTitle(r)}</b>
                  <span>{runLine(r)}</span>
                </button>
              </li>
            ))}
          </ul>
          <TourButton className="btn lk-c-tour" />
        </aside>
        <div className="lk-c-main">
          <SystemMap compact className="lk-c-map" />
          <div className="lk-c-logs" id="desk-panel">
            <div className="lk-c-loghead">
              <b>The desk</b>
              <span>the bill queue, each bill's trace and the decision, as on every layout</span>
            </div>
            <BillDesk />
          </div>
        </div>
      </section>
      <section className="sec lk-sec" id="how">
        <div className="wrap">
          <h2 className="h2">How a bill moves across the canvas</h2>
          <Steps />
        </div>
      </section>
      <Proof kind="table" />
      <Built />
      </main>
      <Foot />
    </>
  )
}

/* ---------------------------------------------------------------- 11 · trace waterfall */

// the recorded runs the trace offers: each problem the lookups looked into, and a clean bill
const TRACE_RUNS = ['03', '06', '08', '10', '12', '09'].map((s) => RUNS.find((r) => r.sample === s)).filter((r): r is RecordedRun => !!r)

function Waterfall({ choice }: PageProps) {
  const [sample, setSample] = useState(TRACE_RUNS[0].sample)
  const r = TRACE_RUNS.find((x) => x.sample === sample) ?? TRACE_RUNS[0]
  const spans = useMemo(() => spansOf(r), [r])
  const [sel, setSel] = useState('root')
  const span = spans.find((s) => s.id === sel) ?? spans[0]
  const chips: [string, string][] = [
    ['Model calls', String(r.calls)],
    ['Lookups', String(r.lookups.filter((l) => l.tool !== 'draft_vendor_email').length)],
    ['Tokens', r.usage.reduce((n, u) => n + u.tokens, 0).toLocaleString('en-US')],
    ['Seconds', r.seconds.toFixed(1)],
    ['Cost', money(r.cost_usd)],
    ['Flagged', String(r.flags.length)],
  ]
  return (
    <>
      <Nav choice={choice} links={[['#trace', 'Trace'], ['#map', 'System map'], ['#try', 'The desk'], ['#proof', 'Results']]} />
      <main>
      <div className="wrap">
        <BeforeAfter />
      </div>
      <section className="lk-w-head wrap" id="trace">
        <p className="lk-crumb">
          Traces <span>/</span> recorded real runs <span>/</span> <b>{r.number}</b>
        </p>
        <div className="lk-w-top">
          <div>
            <h1 className="h1">{runTitle(r)}</h1>
            <p className="lede">Every recorded run as a trace: each model call with the tokens it used, each check and each lookup. Pick a row to see it, and where it sits on the map.</p>
          </div>
          <dl className="lk-w-chips">
            {chips.map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
        </div>
        <div className="lk-w-tabs" role="group" aria-label="Recorded real runs">
          {TRACE_RUNS.map((x) => (
            <button
              type="button"
              key={x.sample}
              aria-pressed={x.sample === sample}
              onClick={() => {
                setSample(x.sample)
                setSel('root')
                playRun(x, 'trace')
              }}
            >
              {runTitle(x)}
            </button>
          ))}
        </div>
        <div className="lk-w-grid">
          <div className="lk-w-tree" role="group" aria-label="The run's steps">
            <div className="lk-w-row lk-w-th" aria-hidden="true">
              <span>Step</span>
              <span>Share of the run's tokens, for a model call</span>
            </div>
            {spans.map((s) => (
              <button type="button" key={s.id} aria-pressed={s.id === span.id} className={`lk-w-row k-${s.kind}${s.bad ? ' bad' : ''}${s.id === span.id ? ' on' : ''}`} onClick={() => setSel(s.id)}>
                <span className="lk-w-name" style={{ paddingLeft: 6 + s.depth * 16 }}>
                  <i className="lk-w-dot" />
                  <b>{s.name}</b>
                  <small>{s.detail}</small>
                </span>
                <span className="lk-w-bar">
                  <i style={{ width: s.share > 0 ? `${Math.max(1.2, s.share * 100).toFixed(1)}%` : undefined }} className={s.share > 0 ? '' : 'mark'} />
                  <em>{s.value}</em>
                </span>
              </button>
            ))}
          </div>
          <aside className="lk-w-span" aria-live="polite">
            <p className="lk-w-kind">{span.kind === 'root' ? 'Run' : 'Step'}</p>
            <h2 className="h3">{span.name}</h2>
            <dl>
              {span.attrs.map(([k, v], i) => (
                <div key={i}>
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
            <p className="lk-w-where">
              On the map: <b>{nodeOf(span.node).label}</b>. {nodeOf(span.node).info}
            </p>
          </aside>
        </div>
      </section>
      <section className="lk-w-map wrap" id="map">
        <h2 className="h2">The same run on the system map</h2>
        <SystemMap focus={span.node} />
      </section>
      <section className="sec lk-sec" id="try">
        <div className="wrap">
          <h2 className="h2">The bill desk</h2>
          <p className="lk-note">The queue a bookkeeper opens: every bill read and checked, each with its trace and a suggested next step.</p>
          <DeskBox />
        </div>
      </section>
      <section className="sec lk-sec lk-tight" id="how">
        <div className="wrap">
          <h2 className="h2">How it works</h2>
          <Steps />
        </div>
      </section>
      <Proof kind="cards" />
      <Built />
      </main>
      <Foot />
    </>
  )
}

/* ---------------------------------------------------------------- 12 · workshop sheet */

function Workshop({ choice }: PageProps) {
  const tabs = [...TOOLS, 'checks']
  const [tab, setTab] = useState('get_purchase_order')
  const isChecks = tab === 'checks'
  const call = isChecks ? null : firstCall(tab)
  const focus = isChecks ? 'checks' : `tool:${tab}`
  return (
    <>
      <Nav choice={choice} links={[['#tools', 'Lookups'], ['#map', 'System map'], ['#try', 'The desk'], ['#proof', 'Results']]} />
      <main>
      <header className="lk-k-hero wrap">
        <p className="eyebrow">
          [ <b>{COMPANY}</b> · accounts payable · {SITE.model.name} ]
        </p>
        <h1 className="h1">Everything the agent can look up, and every check, on one sheet.</h1>
        <p className="lede">{LEDE}</p>
        <div className="btns">
          <DeskLink className="btn go" />
          <TourButton />
        </div>
      </header>
      <div className="wrap">
        <BeforeAfter />
      </div>
      <section className="lk-k-sheet wrap" id="tools">
        <div className="lk-k-tabs" role="tablist" aria-label="The agent's lookups and the checks">
          {tabs.map((t) => (
            <button type="button" role="tab" key={t} aria-selected={t === tab} className={t === tab ? 'on' : ''} onClick={() => setTab(t)}>
              {t === 'checks' ? `${SITE.checks} checks` : toolLabel(t)}
            </button>
          ))}
        </div>
        <div className="lk-k-panel" role="tabpanel">
          <div className="lk-k-text">
            {isChecks ? (
              <>
                <h2 className="h2">{SITE.checks} checks, in code</h2>
                <p>Run on every bill after it is read, before anyone pays it. A flag holds the bill for a person with a suggested next step.</p>
                <ul className="lk-k-rules">
                  {FLAG_CODES.map((c) => (
                    <li key={c}>
                      <b>{flagWords(c).charAt(0).toUpperCase() + flagWords(c).slice(1)}</b>
                      <code>{c}</code>
                      <span>{flaggedBy(c) ? `flagged ${flaggedBy(c)} of ${SITE.recorded.n} recorded bills` : 'no recorded bill tripped it'}</span>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <>
                <h2 className="h2">{toolLabel(tab)}</h2>
                <p>{nodeOf(`tool:${tab}`).info}</p>
                <dl className="lk-k-facts">
                  <div>
                    <dt>Tool</dt>
                    <dd>
                      <code>{tab}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>Reads</dt>
                    <dd>{READS[tab]}</dd>
                  </div>
                </dl>
              </>
            )}
          </div>
          <div className="lk-k-call">
            <p className="lk-k-lab">{isChecks ? 'A real catch' : 'A real call'}</p>
            {isChecks ? (
              <CheckCatch />
            ) : call ? (
              <>
                <p className="lk-k-q">{billTitle(call.run)}</p>
                <div className="lk-k-io">
                  <span>in</span>
                  <b>{call.input || 'no input'}</b>
                  <span>out</span>
                  <b>{call.result}</b>
                </div>
                <button type="button" className="btn" onClick={() => playRun(call.run, 'sheet')}>
                  Play this run on the map
                </button>
              </>
            ) : (
              <p className="lk-k-none">None of the {SITE.recorded.n} recorded bills needed it.</p>
            )}
            <p className="lk-k-src">{nodeOf(focus).info}</p>
          </div>
        </div>
      </section>
      <section className="lk-k-map wrap" id="map">
        <SystemMap focus={focus} onPick={(id) => (id.startsWith('tool:') ? setTab(id.slice(5)) : id === 'checks' ? setTab('checks') : null)} />
      </section>
      <section className="sec lk-sec" id="try">
        <div className="wrap">
          <h2 className="h2">Try it</h2>
          <DeskBox />
        </div>
      </section>
      <section className="sec lk-sec lk-tight" id="how">
        <div className="wrap">
          <h2 className="h2">How it works</h2>
          <Steps />
        </div>
      </section>
      <Proof kind="versus" />
      <Built />
      </main>
      <Foot />
    </>
  )
}

function CheckCatch() {
  // the overcharge: the check found the amount, then the agent looked it up
  const r = RUNS.find((x) => x.flags.some((f) => f.code === 'PRICE_VARIANCE')) ?? RUNS.find((x) => x.flags.length)
  if (!r) return <p className="lk-k-none">No recorded bill was flagged.</p>
  const f = r.flags[0]
  return (
    <>
      <p className="lk-k-q">{billTitle(r)}</p>
      <div className="lk-k-io">
        <span>check</span>
        <b>{flagWords(f.code)}</b>
        <span>found</span>
        <b>
          {f.detail}
          {f.amount ? ` (${amount(f.amount)})` : ''}
        </b>
      </div>
      <button type="button" className="btn" onClick={() => playRun(r, 'sheet')}>
        Play this run on the map
      </button>
    </>
  )
}

/* ---------------------------------------------------------------- 13 · spec sheet */

const SPEC = [
  ['s1', 'System'],
  ['try', 'The desk'],
  ['s3', 'Checks'],
  ['proof', 'Results'],
  ['built', 'Build'],
] as const

const CALLOUTS: [string, string][] = [
  ['read', 'The reading'],
  ['sources', 'The source check'],
  ['checks', 'The checks'],
  ['agent', 'The agent'],
  ['playbook', 'The next step'],
  ['person', 'The decision'],
  ['sign', 'The signature'],
]

function Spec({ choice }: PageProps) {
  const [cur, setCur] = useState('s1')
  const [focus, setFocus] = useState<string | null>(null)
  useEffect(() => {
    const els = SPEC.map(([id]) => document.getElementById(id)).filter(Boolean) as HTMLElement[]
    const io = new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting && setCur(e.target.id)), { rootMargin: '-40% 0px -55% 0px' })
    els.forEach((e) => io.observe(e))
    return () => io.disconnect()
  }, [])
  return (
    <>
      <Nav choice={choice} links={[['#s1', 'System'], ['#try', 'The desk'], ['#s3', 'Checks'], ['#proof', 'Results']]} />
      <main>
      <div className="wrap">
        <BeforeAfter />
      </div>
      <div className="lk-s wrap">
        <nav className="lk-s-index" aria-label="On this page">
          {SPEC.map(([id, t], i) => (
            <a key={id} href={`#${id}`} className={cur === id ? 'on' : ''} aria-current={cur === id ? 'true' : undefined}>
              <span>{String(i + 1).padStart(2, '0')}</span> {t}
            </a>
          ))}
        </nav>
        <div className="lk-s-main">
          <section id="s1" className="lk-s-sec">
            <p className="lk-s-eye">
              <i /> The bill desk · {SITE.model.name}
            </p>
            <h1 className="h1">Read by a model, checked by code, decided by a person.</h1>
            <div className="lk-s-para">
              <span>01</span>
              <p>{LEDE}</p>
            </div>
            <div className="btns">
              <DeskLink className="btn go" />
              <TourButton />
            </div>
            <figure className="lk-s-fig" id="map">
              <figcaption>
                <span>Fig 1.A</span> The bill desk, end to end
              </figcaption>
              <SystemMap focus={focus} onPick={setFocus} />
            </figure>
            <ol className="lk-s-callouts">
              {CALLOUTS.map(([id, t], i) => (
                <li key={id}>
                  <button type="button" aria-pressed={focus === id} onClick={() => setFocus(focus === id ? null : id)}>
                    <span>[1.A.{i + 1}]</span> {t}
                  </button>
                  <p>{nodeOf(id).info}</p>
                </li>
              ))}
            </ol>
          </section>
          <section id="try" className="lk-s-sec">
            <p className="lk-s-eye">
              <i /> 02 · The desk
            </p>
            <h2 className="h2">Open a bill, or walk through a morning.</h2>
            <figure className="lk-s-fig">
              <figcaption>
                <span>Fig 2</span> The desk: the bill queue, each bill's trace, the decision
              </figcaption>
              <div className="lk-s-desk">
                <BillDesk />
              </div>
            </figure>
          </section>
          <section id="s3" className="lk-s-sec">
            <p className="lk-s-eye">
              <i /> 03 · Checks
            </p>
            <h2 className="h2">{SITE.checks} checks, run by code after the model reads the bill.</h2>
            <div className="lk-s-table">
              <table>
                <thead>
                  <tr>
                    <th>No.</th>
                    <th>Check</th>
                    <th>In code</th>
                    <th className="n">Recorded bills flagged</th>
                  </tr>
                </thead>
                <tbody>
                  {FLAG_CODES.map((c, i) => (
                    <tr key={c}>
                      <td className="mono">[3.{i + 1}]</td>
                      <td>{flagWords(c).charAt(0).toUpperCase() + flagWords(c).slice(1)}</td>
                      <td>
                        <code>{c}</code>
                      </td>
                      <td className="n">
                        {flaggedBy(c)} of {SITE.recorded.n}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Steps className="lk-s-steps" />
          </section>
          <Proof kind="numbers" />
          <Built />
        </div>
      </div>
      </main>
      <Foot />
    </>
  )
}

/* ---------------------------------------------------------------- 14 · status cards */

type Card = { id: string; node: string | null; title: string; status: string; tone?: 'bad' | 'ok'; icon: ReactNode }

const I = (d: string) => (
  <svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true">
    <path d={d} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)
const ICON = {
  doc: I('M7 3h7l4 4v14H7zM14 3v4h4M10 12h5M10 16h5'),
  chip: I('M8 8h8v8H8zM4 10h4M4 14h4M16 10h4M16 14h4M10 4v4M14 4v4M10 16v4M14 16v4'),
  check: I('M5 12l4 4 10-10'),
  shield: I('M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3zM9 12l2 2 4-4'),
  search: I('M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4'),
  arrow: I('M5 12h14M13 6l6 6-6 6'),
  person: I('M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0'),
  pen: I('M4 20l4-1 11-11-3-3L5 16zM14 6l3 3'),
  book: I('M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3zM5 17a3 3 0 0 1 3-3h11'),
  coin: I('M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v10M9.5 9.5c0-1 1-1.6 2.5-1.6s2.5.7 2.5 1.6-1 1.4-2.5 1.6-2.5.6-2.5 1.6 1 1.6 2.5 1.6 2.5-.6 2.5-1.6'),
  flask: I('M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3'),
  list: I('M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01'),
}

function Garage({ choice }: PageProps) {
  const [focus, setFocus] = useState<string | null>(null)
  const motion = useMotion()
  const flagged = RUNS.filter((r) => r.flags.length).length
  const found = RUNS.reduce((n, r) => n + r.source_checks.ok, 0)
  const missing = RUNS.reduce((n, r) => n + r.source_checks.missing, 0)
  const photo = RUNS.reduce((n, r) => n + r.source_checks.not_checked, 0) // a photo has no text layer: checked by eye, not failed
  const cards: Card[] = [
    { id: 'read', node: 'read', title: 'Reading', status: `${SITE.model.name}, ${SITE.recorded.n} bills recorded`, icon: ICON.doc },
    { id: 'sources', node: 'sources', title: 'Source check', status: `${found} quoted lines found in the PDF, ${missing} missing, ${photo} photo fields checked by eye`, tone: missing ? 'bad' : 'ok', icon: ICON.search },
    { id: 'checks', node: 'checks', title: 'Checks in code', status: `${SITE.checks} checks · ${flagged} of ${SITE.recorded.n} bills flagged`, tone: flagged ? 'bad' : undefined, icon: ICON.check },
    { id: 'agent', node: 'agent', title: 'Lookups', status: `read-only, at most ${SITE.policies.max_lookups} a bill`, icon: ICON.chip },
    { id: 'playbook', node: 'playbook', title: 'Next step', status: 'worked out by code', icon: ICON.arrow },
    { id: 'person', node: 'person', title: 'A person decides', status: `${controllerFrom()} or more: the controller`, icon: ICON.person },
    { id: 'sign', node: 'sign', title: 'Signed approval', status: 'Ed25519, verified by the books', icon: ICON.pen },
    { id: 'erp', node: 'erp', title: 'The books', status: 'a mock ERP that checks every signature', icon: ICON.book },
    { id: 'audit', node: 'audit', title: 'Audit trail', status: 'insert-only, hash-chained', icon: ICON.list },
    { id: 'qbo', node: 'qbo', title: 'QuickBooks', status: 'a sandbox copy, when switched on', icon: ICON.shield },
    { id: 'cost', node: null, title: 'Cost a bill', status: COST_RANGE, icon: ICON.coin },
    { id: 'tests', node: null, title: 'Tests', status: `${TESTS} of ${TESTS} passing`, tone: 'ok', icon: ICON.flask },
  ]
  const toMap = () => document.getElementById('map')?.scrollIntoView({ behavior: motion ? 'smooth' : 'auto', block: 'start' })
  const tap = (c: Card) => {
    if (!c.node) return
    setFocus(c.node)
    toMap()
  }
  return (
    <>
      <Nav choice={choice} center links={[['#status', 'Status'], ['#try', 'The desk'], ['#map', 'Map'], ['#proof', 'Results']]} />
      <main className="lk-g wrap">
        <section className="lk-g-hello" id="status">
          <h1 className="h1">
            {SITE.recorded.n} bills checked.
            <br />
            {flagged} need a person.
          </h1>
          <p className="lede">{LEDE}</p>
        </section>
        <BeforeAfter />
        <p className="lk-g-label">Desk status</p>
        <div className="lk-g-cards">
          {cards.map((c) => (
            <button type="button" key={c.id} className={`lk-g-card${c.node ? '' : ' still'}${focus && focus === c.node ? ' on' : ''}`} onClick={() => tap(c)} disabled={!c.node} aria-label={`${c.title}: ${c.status}${c.node ? '. Show it on the map' : ''}`}>
              <span className="lk-g-ic">{c.icon}</span>
              <b>{c.title}</b>
              <span className={`lk-g-st${c.tone ? ` ${c.tone}` : ''}`}>{c.status}</span>
            </button>
          ))}
        </div>
        <p className="lk-g-label" id="try">
          The desk
        </p>
        <div className="lk-g-panel">
          <BillDesk />
        </div>
        <p className="lk-g-label" id="map">
          How it works · tap a card above, or any piece
        </p>
        <SystemMap focus={focus} onPick={setFocus} />
        <p className="lk-g-label">The six steps</p>
        <div className="lk-g-panel">
          <Steps />
        </div>
        <p className="lk-g-label">Recorded bills</p>
        <div className="lk-g-runs">
          {RUNS.map((r) => (
            <button type="button" key={r.sample} className="lk-g-card lk-g-run" onClick={() => (playRun(r, 'card'), toMap())}>
              <b>{runTitle(r)}</b>
              <span className={`lk-g-st${r.flags.length ? ' bad' : ''}`}>{runLine(r)}</span>
            </button>
          ))}
        </div>
      </main>
      <Proof kind="numbers" />
      <Built />
      <Foot />
      <nav className="lk-g-tabbar" aria-label="Jump to">
        {(
          [
            ['#status', 'Status', ICON.check],
            ['#try', 'Desk', ICON.doc],
            ['#map', 'Map', ICON.chip],
            ['#proof', 'Results', ICON.coin],
          ] as [string, string, ReactNode][]
        ).map(([h, t, ic]) => (
          <a key={h} href={h}>
            {ic}
            <span>{t}</span>
          </a>
        ))}
      </nav>
    </>
  )
}
