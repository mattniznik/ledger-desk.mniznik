// The four section-built layouts (01, 04, 05, 06): a nav, a hero holding the bill desk, the system map, what the
// checks catch, how a bill moves through, the measured results, how it was built, and the footer, each in the variant
// the layout names (studio/presets.ts). Every number comes from site-data.json (site.ts).

import { useEffect, useState } from 'react'

import './rich.css'
import { Desk } from '../Desk.tsx'
import { BeforeAfter } from '../shared/BeforeAfter.tsx'
import { Studio } from '../studio/Studio.tsx'
import type { Cfg, Choice } from '../studio/choice.ts'
import { Built } from '../shared/Built.tsx'
import { Field, Pipeline, Player, Story } from '../shared/How.tsx'
import { SystemMapSection } from '../shared/SystemMap.tsx'
import { COMPANY, COST_RANGE, COST_TOTAL, DISCLAIMER, LEDE, SITE, STACK, TEST_FILES, TESTS } from '../shared/data.ts'
import { jumpToDesk, useMotion } from '../live.ts'
import { amount, billTitle, drafted, flagWords, howSub, logLines, modelRun, money, runOf, toolCount, type HowKind, type RecordedRun } from '../site.ts'

const rec = SITE.recorded
const std = modelRun('standard')
const titleOf = (r: RecordedRun) => billTitle(r)

export function RichPage({ cfg, choice }: { cfg: Cfg; choice: Choice }) {
  useEffect(() => document.documentElement.classList.remove('boot'), [])
  return (
    <>
      <Nav choice={choice} />
      <main>
      <div data-slot="hero">{cfg.hero === 'console' ? <HeroConsole /> : cfg.hero === 'split' ? <HeroSplit /> : cfg.hero === 'editorial' ? <HeroEditorial /> : <HeroDesk />}</div>
      <div className="wrap">
        <SystemMapSection />
      </div>
      <div data-slot="features">{cfg.features === 'bento' ? <Bento /> : cfg.features === 'list' ? <List /> : null}</div>
      <How kind={cfg.how ?? 'field'} />
      <Proof kind={cfg.proof ?? 'numbers'} />
      <Built />
      </main>
      <Footer />
    </>
  )
}

/* ---------------------------------------------------------------- nav and footer */

export function DeskLink({ className, children = 'Open the desk' }: { className: string; children?: string }) {
  const motion = useMotion()
  return (
    <a className={className} href="#desk" onClick={(e) => (e.preventDefault(), jumpToDesk(motion))}>
      {children}
    </a>
  )
}

function Nav({ choice }: { choice: Choice }) {
  return (
    <nav className="nav" aria-label="Sections">
      <div className="wrap">
        <span className="brand">
          <i />
          {COMPANY}
        </span>
        <Studio choice={choice} placement="nav" />
        <span className="links">
          <a href="#map">System map</a>
          <a href="#how">How it works</a>
          <a href="#proof">Results</a>
          <a href="#built">How it was built</a>
        </span>
        <DeskLink className="btn go small" />
      </div>
    </nav>
  )
}

function Footer() {
  return (
    <footer className="foot">
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
            <a className="btn" href="#how">
              How it works
            </a>
          </div>
        </div>
      </div>
    </footer>
  )
}

/* ---------------------------------------------------------------- heroes */

// the problem and what this does, then the desk itself: the same order on every layout
const DeskStage = ({ className = '' }: { className?: string }) => (
  <>
    <BeforeAfter />
    <div className={`desk-stage ${className}`}>
      <Desk />
    </div>
  </>
)

function HeroDesk() {
  return (
    <section className="hero-search sec" id="top">
      <div className="glow" />
      <div className="wrap">
        <p className="eyebrow">
          [ <b>{COMPANY}</b> · accounts payable · {SITE.model.name} ]
        </p>
        <h1 className="h1">
          Supplier bills,
          <br />
          <span className="grad">checked before they are paid.</span>
        </h1>
        <p className="lede">{LEDE}</p>
        <DeskStage className="center" />
        <div className="trust">
          <span>{rec.n} real runs recorded</span>
          <span>{SITE.checks} checks in code</span>
          <span>{COST_RANGE} per bill</span>
          {std && (
            <span>
              {std.fields_correct} of {std.fields} fields read right
            </span>
          )}
        </div>
      </div>
    </section>
  )
}

const TERM_RUNS = ['03', '07', '08', '12']

function Terminal() {
  const motion = useMotion()
  const [key, setKey] = useState(TERM_RUNS[0])
  const [shown, setShown] = useState(0)
  const r = runOf(key)
  const lines = logLines(r)
  useEffect(() => {
    if (!motion) return
    const t = setInterval(() => setShown((n) => (n > lines.length ? (clearInterval(t), n) : n + 1)), 420)
    return () => clearInterval(t)
  }, [key, motion, lines.length])
  // reduced motion: the whole run at once
  const visible = motion ? shown : lines.length + 1
  const pickRun = (k: string) => {
    setKey(k)
    setShown(0)
  }
  return (
    <div className="term">
      <div className="bar">
        <i />
        <i />
        <i />
        <span>ledger desk · recorded real run</span>
      </div>
      <div className="runs" role="group" aria-label="Recorded runs">
        {TERM_RUNS.map((k) => (
          <button type="button" key={k} data-ex={k} aria-pressed={k === key} onClick={() => pickRun(k)}>
            {runOf(k).number}
          </button>
        ))}
      </div>
      <div className="body">
        <div className="cmd">
          $ run <b>{titleOf(r)}</b>
        </div>
        {lines.map((l, i) => (
          <div key={`${key}-${i}`} className={`ln${i < visible ? ' on' : ''}`}>
            <span className={`k ${l.k}`}>{l.k}</span>
            <span className="d">{l.d}</span>
            <span className="t" />
          </div>
        ))}
        {r.explanation && <div className={`out${visible > lines.length ? ' on' : ''}`}>{r.explanation}</div>}
        <div className={`ln${visible > lines.length ? ' on' : ''}`}>
          <span className="k">cost</span>
          <span className="d">
            {r.calls} model calls · {r.seconds.toFixed(1)} s · {money(r.cost_usd)}
          </span>
          <span className="t" />
        </div>
      </div>
    </div>
  )
}

function HeroConsole() {
  return (
    <section className="hero-console sec" id="top">
      <div className="wrap">
        <div className="grid">
          <div>
            <p className="eyebrow">
              [ <b>Under the hood</b> · {COMPANY} ]
            </p>
            <h1 className="h1">
              Every bill <span className="grad">shows its work.</span>
            </h1>
            <p className="lede">
              One model, {SITE.checks} checks written in code, and a person who decides. Each run on the right is a recorded real one: what was
              read, what the checks found, every lookup, and where it stopped for a person.
            </p>
          </div>
          <Terminal />
        </div>
        <DeskStage />
      </div>
    </section>
  )
}

function HeroSplit() {
  const r = runOf('03')
  const f = r.flags[0]
  return (
    <section className="hero-split sec" id="top">
      <div className="wrap">
        <div className="grid">
          <div>
            <p className="eyebrow">
              [ <b>What the checks found</b> ]
            </p>
            <h1 className="h1 h1-split">
              The bill, <span className="grad">and what code found in it.</span>
            </h1>
            <p className="lede">
              Claude reads every supplier bill. Code checks it against the purchase order, what was delivered, the paid bills and the bank
              details on file, before anyone pays it.
            </p>
            <ul className="promises">
              <li>
                <span className="ic">✓</span>
                <span>Prices within {SITE.policies.price_tolerance_percent}% of the purchase order, or the bill waits</span>
              </li>
              <li>
                <span className="ic">⌖</span>
                <span>Every bill matched against the paid bills, so a copy is caught</span>
              </li>
              <li>
                <span className="ic">!</span>
                <span>A new bank account held until the controller calls the number on file</span>
              </li>
            </ul>
          </div>
          <div className="mock">
            <div className="page fade">
              <div className="ph">
                <span>
                  {r.vendor} · {r.number}
                </span>
                <span>{amount(r.total)}</span>
              </div>
              <div className="fake" style={{ width: '92%' }} />
              <div className="fake" style={{ width: '76%' }} />
              {f && (
                <div>
                  <mark>{flagWords(f.code)}</mark>
                  {f.amount ? ` - ${amount(f.amount)}` : ''}
                </div>
              )}
              <div className="fake" style={{ width: '88%' }} />
              <div className="fake" style={{ width: '64%' }} />
              {f && <p className="rule-note">The check reads: {f.detail}.</p>}
            </div>
            <div className="wire" />
            <div className="float">
              <div className="card finding-card fade">
                <div className="top">
                  <span className="pill ok">Real run</span>
                  <span className="mono muted small">
                    {money(r.cost_usd)} · {r.seconds.toFixed(1)} s
                  </span>
                </div>
                <p className="q">What the AI found</p>
                <p className="a">{r.explanation}</p>
              </div>
            </div>
          </div>
        </div>
        <DeskStage />
      </div>
    </section>
  )
}

function HeroEditorial() {
  const r = runOf('07')
  return (
    <section className="hero-editorial sec" id="top">
      <div className="wrap">
        <div className="grid">
          <div>
            <p className="eyebrow">No. 01 · A bill a vendor sent twice</p>
            <h1 className="h1">Invoice {r.number} arrived again.</h1>
            {/* what code found, not the model's recorded words: its explanation of this bill calls the bill's own date a
                payment date, and a headline should not repeat that */}
            <p className="pull">
              This copy of {r.number} is already among the paid bills. Paying it would send {r.vendor} the same {amount(r.total)} twice, so the
              suggested next step rejects it.
              <sup>1</sup>
            </p>
            <ol className="footnotes">
              <li>
                <b>1</b>
                <span>
                  Code matched the bill number against the company's paid bills. Claude then looked up the vendor's paid bills itself and drafted a
                  note telling the vendor it was already paid; nothing is sent without a person.
                </span>
              </li>
            </ol>
            <p className="desk-intro">Try the desk, or walk through a morning in accounts payable:</p>
            <DeskStage />
          </div>
          <aside className="side-note">
            <div className="h3">Every finding was checked</div>
            <p className="muted">
              The AI explains; code decides. Each bill is checked against the purchase order, the delivery, the paid bills and the bank details
              on file, and nothing is paid until a person approves.
            </p>
            <p className="mono small">
              {rec.matched} of {rec.n} recorded bills end as their answer key says · {COST_RANGE} per bill
            </p>
          </aside>
        </div>
      </div>
    </section>
  )
}

/* ---------------------------------------------------------------- what the checks catch */

const firstLookup = (r: RecordedRun) => logLines(r).find((l) => l.k === 'lookup' || l.k === 'check')?.d ?? ''

function Bento() {
  const over = runOf('03'), dup = runOf('07'), bank = runOf('08'), ai = runOf('12'), clean = runOf('09')
  return (
    <section className="sec" id="features">
      <div className="wrap">
        <div className="sec-head">
          <h2 className="h2">
            What it catches, <span className="grad">before anyone pays.</span>
          </h2>
          <p>Each tile is a recorded real run on one of the sample bills, not a mock-up.</p>
        </div>
        <div className="bento">
          <div className="tile w4">
            <div className="mini-quote mono small">
              {titleOf(over)} · {firstLookup(over)}
            </div>
            <div className="mini-row" style={{ marginTop: 10 }}>
              <span className="cite">{over.flags[0] ? amount(over.flags[0].amount ?? 0) : ''} over</span>
            </div>
            <div className="h3">An overcharge, caught</div>
            <p>Every line is compared with the purchase order price; the AI looks up the order and the delivery and drafts the email to the vendor.</p>
          </div>
          <div className="tile w2">
            <div className="mini-row muted">{titleOf(dup)}</div>
            <div className="mini-row" style={{ marginTop: 12 }}>
              <span className="pill nf">{flagWords('DUPLICATE')}</span>
            </div>
            <div className="h3">A bill sent twice</div>
            <p>Every bill is matched against the paid bills, so the copy is rejected instead of paid.</p>
          </div>
          <div className="tile w3">
            <div className="mini-row">
              <span className="pill held">{flagWords(bank.flags[0]?.code ?? 'BANK_CHANGED')}</span>
            </div>
            <div className="mini-row" style={{ marginTop: 10 }}>
              <span className="pill ok">held for the controller</span>
            </div>
            <div className="h3">A new bank account, held</div>
            <p>Only the controller can approve it, after calling the vendor on the number already on file, never one from the bill.</p>
          </div>
          <div className="tile w3">
            <div className="mini-quote mono small">{titleOf(ai)}</div>
            <div className="mini-row" style={{ marginTop: 10 }}>
              <span className="pill held">{flagWords('SUSPICIOUS_TEXT')}</span>
            </div>
            <div className="h3">Text aimed at the AI, flagged</div>
            <p>A bill that tries to instruct the AI is treated as data and held for a person; the AI has no tool that could pay it.</p>
          </div>
          <div className="tile w2">
            <div className="mini-row">
              <span className="pill ok">account {clean.account}</span>
            </div>
            <div className="h3">Coded, then checked</div>
            <p>With no purchase order, Claude suggests the account and code accepts it only if it fits the vendor.</p>
          </div>
          <div className="tile w4 money">
            <div>
              <div className="big grad">{COST_TOTAL}</div>
              <p>for all {rec.n} recorded real runs</p>
            </div>
            <div className="money-text">
              <div className="h3">Measured, run by run</div>
              <p>
                {COST_RANGE} per bill at API list prices, from the tokens {SITE.model.name} reported. The demo replays them at no cost.
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

function List() {
  const items: [string, string, string][] = [
    ['✓', 'Prices checked against the order', `A line more than ${SITE.policies.price_tolerance_percent}% above the purchase order price holds the bill.`],
    ['⌖', 'Paid once, not twice', 'Every bill is matched against the paid bills; a copy is rejected.'],
    ['!', 'Bank changes held', 'Only the controller approves a new bank account, after a call to the number on file.'],
    ['⚙', 'Read with its sources', std ? `Each field comes with the line it was read from; ${std.fields_correct} of ${std.fields} right in the eval.` : 'Each field comes with the line it was read from.'],
    ['→', 'A person decides', 'Each problem bill arrives with a suggested next step; nothing is paid until a person approves.'],
    ['$', `${COST_RANGE} per bill`, `At API list prices, from the token counts of ${rec.n} real runs of ${SITE.model.name}.`],
  ]
  return (
    <section className="sec" id="features">
      <div className="wrap">
        <div className="sec-head">
          <h2 className="h2">
            {items.length} promises, <span className="grad">each one checked.</span>
          </h2>
          <p>Each line is a check in code or a number measured on recorded real runs.</p>
        </div>
        <div className="ilist">
          {items.map(([i, h, p]) => (
            <div className="it" key={h}>
              <span className="ic">{i}</span>
              <div>
                <div className="h3">{h}</div>
                <p>{p}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

/* ---------------------------------------------------------------- how a bill moves through */

function How({ kind }: { kind: HowKind }) {
  return (
    <section className="sec" id="how">
      <div className="wrap">
        <div className="sec-head">
          <h2 className="h2">
            How a bill <span className="grad">moves through.</span>
          </h2>
          <p>{howSub(kind)}</p>
        </div>
        {kind === 'pipeline' ? <Pipeline /> : kind === 'story' ? <Story /> : kind === 'player' ? <Player /> : <Field />}
      </div>
    </section>
  )
}

/* ---------------------------------------------------------------- the measured results */

function ProofHead() {
  return (
    <div className="sec-head">
      <h2 className="h2">
        Measured, <span className="grad">not promised.</span>
      </h2>
      <p>
        {rec.n} real runs of {SITE.model.name}, each with the tokens and time it reported and its cost at API list prices, and {TESTS} tests,
        all passing when this page was built.
      </p>
    </div>
  )
}

const EvalsLine = () => <p className="small-print">Every eval run, with each miss, is under How it works in the desk.</p>

export function Proof({ kind }: { kind: 'numbers' | 'table' | 'cards' | 'versus' }) {
  const [seen, setSeen] = useState(false)
  const motion = useMotion()
  // the bars and numbers grow the first time the section scrolls into view; with reduced motion they are there at once
  const watch = motion && typeof window !== 'undefined' && 'IntersectionObserver' in window
  useEffect(() => {
    const el = document.getElementById('proof')
    if (!watch || !el) return
    const io = new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting && (setSeen(true), io.disconnect())), { threshold: 0.2 })
    io.observe(el)
    return () => io.disconnect()
  }, [watch])
  const inView = seen || !watch
  const body = kind === 'table' ? <ProofTable /> : kind === 'cards' ? <ProofCards /> : kind === 'versus' ? <ProofVersus /> : <ProofNumbers />
  return (
    <section className={`sec${inView ? ' in' : ''}`} id="proof">
      <div className="wrap">
        {kind !== 'table' && <ProofHead />}
        {body}
        <EvalsLine />
      </div>
    </section>
  )
}

function ProofNumbers() {
  const cells: [string, string][] = [
    [String(rec.n), 'real runs recorded, replayed on this page at no cost'],
    [COST_TOTAL, `at API list prices for all of them, ${COST_RANGE} each`],
    [`${rec.matched}/${rec.n}`, 'bills ended exactly as their answer key says'],
    [String(TESTS), `tests in ${TEST_FILES} files, all passing`],
  ]
  return (
    <div className="numrow">
      {cells.map(([v, l]) => (
        <div className="c" key={l}>
          <div className="v grad">{v}</div>
          <div className="l">{l}</div>
        </div>
      ))}
    </div>
  )
}

function ProofTable() {
  return (
    <>
      <div className="evhead">
        <div className="v grad">{rec.n}</div>
        <div>
          <div className="h3">real runs of {SITE.model.name}: tokens and time as reported, cost at API list prices</div>
          <p className="muted" style={{ margin: '4px 0 0' }}>
            Tokens and seconds as reported, cost at API list prices: {COST_TOTAL} for all of them. {rec.matched} of {rec.n} bills ended exactly as their answer key
            says.
          </p>
        </div>
      </div>
      <div className="tablewrap">
        <table className="evtable">
          <thead>
            <tr>
              <th>Bill</th>
              <th className="n">Model calls</th>
              <th className="n">Lookups</th>
              <th className="n">Seconds</th>
              <th className="n">Cost</th>
            </tr>
          </thead>
          <tbody>
            {rec.runs.map((r) => (
              <tr key={r.sample}>
                <td>
                  {titleOf(r)}
                  {r.flags.length === 0 && <span className="pill ok tiny">clean</span>}
                  {r.flags.map((f) => (
                    <span className="pill held tiny" key={f.code}>
                      {flagWords(f.code)}
                    </span>
                  ))}
                </td>
                <td className="n">{r.calls}</td>
                <td className="n">{toolCount(r)}</td>
                <td className="n">{r.seconds.toFixed(1)}</td>
                <td className="n">{money(r.cost_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function Bars({ rows, unit }: { rows: [string, number, string][]; unit: (v: number) => string }) {
  const max = Math.max(...rows.map((r) => r[1]))
  return (
    <div className="viz hb">
      {rows.map(([l, v, k]) => (
        <div className="r" key={k}>
          <span>{l}</span>
          <span className="tr">
            <i style={{ width: `${Math.max(2, (100 * v) / max).toFixed(1)}%` }} />
          </span>
          <span>{unit(v)}</span>
        </div>
      ))}
    </div>
  )
}

function ProofCards() {
  const dots = rec.runs.map((r) => (r.flags.length ? (drafted(r) ? 'p' : 'h') : 'c'))
  return (
    <div className="mcards">
      <div className="mcard">
        <span className="k">Cost</span>
        <div className="h3">{COST_TOTAL} for all of them</div>
        <p>Per bill, at API list prices from the tokens reported.</p>
        <Bars rows={rec.runs.map((r) => [r.number, r.cost_usd, r.sample])} unit={(v) => money(v)} />
      </div>
      <div className="mcard">
        <span className="k">Time</span>
        <div className="h3">
          {rec.seconds.min.toFixed(1)} to {rec.seconds.max.toFixed(1)} s
        </div>
        <p>From the bill to the pause for a person, per run.</p>
        <Bars rows={rec.runs.map((r) => [r.number, r.seconds, r.sample])} unit={(v) => v.toFixed(1) + ' s'} />
      </div>
      <div className="mcard">
        <span className="k">The checks</span>
        <div className="h3">
          {rec.runs.filter((r) => r.flags.length).length} of {rec.n} held for a person
        </div>
        <p>One dot per recorded bill.</p>
        <div className="viz">
          <div className="dots big">
            {dots.map((d, i) => (
              <i key={i} className={d} />
            ))}
          </div>
          <div className="leg">
            <span>
              <i style={{ background: 'var(--a1)' }} />
              clean, one click
            </span>
            <span>
              <i style={{ background: 'var(--a2)' }} />
              a problem, email drafted
            </span>
            <span>
              <i style={{ background: 'var(--mu)' }} />
              a problem, held for a person
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

function ProofVersus() {
  const cheap = rec.runs.reduce((a, b) => (b.cost_usd < a.cost_usd ? b : a))
  const dear = rec.runs.reduce((a, b) => (b.cost_usd > a.cost_usd ? b : a))
  return (
    <div className="vs">
      <div className="vbox">
        <div className="v">{money(cheap.cost_usd)}</div>
        <div className="l">the cheapest real run: {titleOf(cheap)}{cheap.flags.length ? '' : ', a clean bill'}</div>
      </div>
      <div className="vbox">
        <div className="v">{money(dear.cost_usd)}</div>
        <div className="l">
          the dearest: {titleOf(dear)}
          {dear.flags.length ? `, ${flagWords(dear.flags[0].code)}` : ''}
        </div>
      </div>
      <div className="vbox">
        <div className="v">{COST_TOTAL}</div>
        <div className="l">for all {rec.n} recorded real runs, at API list prices</div>
      </div>
      <div className="vbox">
        <div className="v">
          {rec.matched} / {rec.n}
        </div>
        <div className="l">bills ended exactly as their answer key says</div>
      </div>
      <div className="vbox wide">
        <div className="v">{TESTS}</div>
        <div className="l">tests in {TEST_FILES} files, all passing</div>
      </div>
    </div>
  )
}
