import { useEffect, useRef, useState } from 'react'
import { type Client, type Run, type Sample, modeLabel, usd } from './api'
import { atRisk, dueLabel, dueText, groupOf, outcome, problemImpact, problemLabel } from './bills'

type Props = { client: Client; onOpen: (runId: string) => void }
type Bill = { sample: Sample; run: Run; held: boolean }

const ROLE: Record<string, string> = { clerk: 'Clerk', controller: 'Controller' }

const amountOf = (b: Bill) => b.run.pause?.total ?? b.run.extraction?.total ?? b.sample.total
const sum = (bills: Bill[]) => usd(bills.reduce((a, b) => a + Number(amountOf(b)), 0))
const count = (n: number) => `${n} ${n === 1 ? 'bill' : 'bills'}`

// On a phone the column headers are hidden, so a bare date gets its "Due" back
function due(run: Run) {
  const text = dueText(run)
  return text && text === dueLabel(run.due_date) ? <><span className="phone-only">Due </span>{text}</> : text
}

// Who may approve, as authority.py decides it; a bill with no entry cannot be approved by anyone yet
function who(run: Run): string {
  if (!run.pause) return ''
  if (run.pause.proposal.lines.length === 0) return 'Not yet: no entry to book'
  return ROLE[run.pause.approver] ?? ''
}

function checksPassed(run: Run): string {
  const e = run.extraction
  if (e && Number(e.total) < 0) return 'Credit memo: reduces what is owed'
  if (e?.po) return `Matches ${e.po} and what was delivered`
  return 'No purchase order; nothing unusual found'
}

// The bill queue a bookkeeper opens on Monday: every bill already read and checked, sorted into what
// needs a look, what is ready to approve and what is done. On a visitor's first visit the 13 sample
// bills are read here (a replay of a recorded real Claude run, $0); after that they come from the
// visitor's session.
export function Inbox({ client, onOpen }: Props) {
  const [samples, setSamples] = useState<Sample[]>([])
  const [runs, setRuns] = useState<Record<string, Run>>({})
  const [held, setHeld] = useState<Set<string>>(new Set())
  const [reading, setReading] = useState<{ done: number; of: number } | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [showKey, setShowKey] = useState(false)
  const [errors, setErrors] = useState<string[]>([])
  // StrictMode runs effects twice in development; reading a bill twice would put it in the queue twice
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true
    const fail = (what: string, e: unknown) => setErrors((x) => [...x, `${what}: ${e instanceof Error ? e.message : String(e)}`])
    ;(async () => {
      const [ss, inv] = await Promise.all([client.samples(), client.invoices()])
      setSamples(ss)
      setHeld(new Set(inv.filter((i) => i.status === 'on_hold' && i.run_id).map((i) => i.run_id as string)))
      const have: Record<string, Run> = {}
      // one bill that cannot be fetched is reported on its own line; it does not blank the queue
      const lookups = inv.filter((i) => i.run_id)
      const found = await Promise.allSettled(lookups.map((i) => client.run(i.run_id as string)))
      found.forEach((f, k) => (f.status === 'fulfilled' ? (have[f.value.sample] = f.value) : fail(`bill ${lookups[k].number}`, f.reason)))
      setRuns({ ...have })
      setLoaded(true)
      const todo = ss.filter((s) => !have[s.id])
      for (let i = 0; i < todo.length; i++) {
        setReading({ done: i, of: todo.length })
        try {
          const r = await client.startRun(todo[i].id, 'replay')
          have[r.sample] = r
          setRuns({ ...have })
        } catch (e) {
          fail(`bill ${todo[i].number}`, e)
        }
      }
      setReading(null)
    })().catch((e) => fail('loading the bills', e))
  }, [client])

  const bills: Bill[] = samples.filter((s) => runs[s.id]).map((s) => ({ sample: s, run: runs[s.id], held: held.has(runs[s.id].run_id) }))
  const needs = bills.filter((b) => groupOf(b.run, b.held ? 'on_hold' : undefined) === 'needs')
  const ready = bills.filter((b) => groupOf(b.run, b.held ? 'on_hold' : undefined) === 'ready')
  const done = bills.filter((b) => groupOf(b.run) === 'done')
  const risk = atRisk(bills.map((b) => b.run))
  const anyRun = bills[0]?.run

  const review = (b: Bill, label = 'Review') => (
    <button aria-label={`${label} ${b.sample.number}`} disabled={reading !== null} onClick={() => onOpen(b.run.run_id)}>{label}</button>
  )
  const billCells = (b: Bill) => (
    <>
      <td className="vendor">{b.sample.vendor_name}</td>
      <td className="invoice">{b.sample.number}{b.sample.document === 'photo' && <span className="btag"> photo</span>}</td>
      <td className="num amount">{usd(amountOf(b))}</td>
    </>
  )

  return (
    <section className="inbox">
      <h2>Bills to pay</h2>
      <p className="intro">
        This week's supplier bills, each read and checked against the purchase order, what was delivered, past bills and the vendor's
        bank details on file. Approve the clean ones; the rest say what is wrong.
      </p>
      {reading && <p className="mode" role="status">Reading new bills: {reading.done} of {reading.of}…</p>}
      {errors.map((e) => <p key={e} role="alert" className="error">{e}</p>)}

      {loaded && (
        <div className="stats">
          <div className="stat" role="group" aria-label="Ready to approve">
            <span className="stat-label">Ready to approve</span>
            <strong>{count(ready.length)} · {sum(ready)}</strong>
            <span className="stat-sub">every check passed</span>
          </div>
          <div className="stat warn" role="group" aria-label="Needs a look">
            <span className="stat-label">Needs a look</span>
            <strong>{count(needs.length)} · {sum(needs)}</strong>
            <span className="stat-sub">held until someone decides</span>
          </div>
          <div className="stat risk" role="group" aria-label="Caught before paying">
            <span className="stat-label">Caught before paying</span>
            <strong>{usd(risk.total)}</strong>
            <span className="stat-sub">
              overcharges, bills already paid and unconfirmed bank accounts, held back or rejected{risk.unpriced.length > 0 && <>; also {risk.unpriced.join(', ')}</>}
            </span>
          </div>
        </div>
      )}

      {loaded && (
        <section aria-label={`Needs a look (${needs.length})`} className="queue">
          <h3>Needs a look ({needs.length})</h3>
          {needs.length === 0 ? <p className="fine">Nothing waiting.</p> : (
            <table>
              <thead><tr><th>Vendor</th><th>Bill</th><th className="num">Amount</th><th>Due</th><th>What is wrong</th><th>Who decides</th><th></th></tr></thead>
              <tbody>
                {needs.map((b) => (
                  <tr key={b.sample.id}>
                    {billCells(b)}
                    <td className="due">{due(b.run)}</td>
                    <td className="problem">
                      {b.held && <span className="btag held">On hold</span>}
                      {!b.run.paused && <span className="flag">{outcome(b.run)}</span>}
                      {b.run.pause?.flags.map((f) => (
                        <div key={f.code}>
                          <span className="flag">{problemLabel(f.code)}</span>
                          {problemImpact(f, amountOf(b)) && <span className="impact">{problemImpact(f, amountOf(b))}</span>}
                        </div>
                      ))}
                      {b.run.paused && b.run.next_step && !b.held && <div className="next">Next: {b.run.next_step.action}</div>}
                    </td>
                    <td className="who">{who(b.run)}</td>
                    <td className="action">{review(b)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      {loaded && (
        <section aria-label={`Ready to approve (${ready.length})`} className="queue">
          <h3>Ready to approve ({ready.length})</h3>
          {ready.length === 0 ? <p className="fine">Nothing waiting.</p> : (
            <table>
              <thead><tr><th>Vendor</th><th>Bill</th><th className="num">Amount</th><th>Due</th><th>Checks</th><th>Who decides</th><th></th></tr></thead>
              <tbody>
                {ready.map((b) => (
                  <tr key={b.sample.id}>
                    {billCells(b)}
                    <td className="due">{due(b.run)}</td>
                    <td className="problem ok-text">{checksPassed(b.run)}</td>
                    <td className="who">{who(b.run)}</td>
                    <td className="action">{review(b)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      {loaded && done.length > 0 && (
        <section aria-label={`Done (${done.length})`} className="queue">
          <h3>Done ({done.length})</h3>
          <table>
            <thead><tr><th>Vendor</th><th>Bill</th><th className="num">Amount</th><th>Result</th><th></th></tr></thead>
            <tbody>
              {done.map((b) => (
                <tr key={b.sample.id}>
                  {billCells(b)}
                  <td className="problem">{outcome(b.run)}</td>
                  <td className="action">{review(b, 'Open')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <aside className="demo-key">
        <p className="fine">
          Demo company: the {samples.length} bills are samples, some clean and some with a problem planted for the checks to find.
          {anyRun && <> They were read by a {modeLabel(anyRun).charAt(0).toLowerCase() + modeLabel(anyRun).slice(1)}.</>}{' '}
          <button className="link" onClick={() => setShowKey((v) => !v)}>{showKey ? 'Hide' : 'Show'} what was planted in each one</button>
        </p>
        {showKey && (
          <table className="key">
            <tbody>
              {samples.map((s) => (
                <tr key={s.id}><td className="id">{s.id}</td><td>{s.vendor_name} {s.number}</td><td className="fine">{s.what_is_wrong}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </aside>
    </section>
  )
}
