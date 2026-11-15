import { useEffect, useState } from 'react'
import type { Client, EvalCase, EvalRun } from './api'
import { modelRun, SITE } from './site'

const pct = (n: number | null) => (n === null ? 'n/a' : n.toFixed(2))

// Every eval run: graded in code against the hand-written answers, no AI judging AI. A scripted
// run reads each invoice perfectly from the answer key, so it proves the graders, not a model;
// the page says so beside it.
export function EvalsPage({ client }: { client: Client }) {
  const [runs, setRuns] = useState<EvalRun[] | null>(null)
  const [open, setOpen] = useState<(EvalRun & { cases: EvalCase[] }) | null>(null)

  useEffect(() => { client.evals().then(setRuns).catch(() => setRuns([])) }, [client])

  if (runs === null) return <p>Loading…</p>
  if (runs.length === 0) return <section className="evals"><h2>Evals</h2><p>No eval runs yet. Run <code>uv run ledger-desk eval</code> to make one.</p></section>

  const std = modelRun('standard')
  const hard = modelRun('hard')
  return (
    <section className="evals">
      <h2>Evals</h2>
      <p className="fine">
        {std ? <>{std.cases} standard invoices ({SITE.recorded.n} samples and {std.cases - SITE.recorded.n} variants)</> : 'The standard invoices'}
        {hard ? <> and a hard tier of {hard.cases}</> : null}, each with its answer written by hand. Reading is graded
        field by field, to the cent; the end result is graded against the expected status, flags, approver and account.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Model</th><th>Tier</th><th className="num">End result</th><th className="num">Fields read</th><th className="num">Account</th><th className="num">Safety</th><th className="num">Cost</th><th className="num">s / invoice</th><th></th></tr>
          </thead>
          <tbody>
            {runs.map((r) => {
              const s = r.summary
              const fields = s.reading.pdf.fields + s.reading.photo.fields
              const correct = s.reading.pdf.fields_correct + s.reading.photo.fields_correct
              return (
                <tr key={r.name}>
                  <td>{r.model}{r.model === 'scripted' && <div className="fine">proves {r.proves}</div>}</td>
                  <td>{r.tier}</td>
                  <td className="num">{s.end_result.exact} / {s.cases}</td>
                  <td className="num">{correct} / {fields}</td>
                  <td className="num">{s.account.top1} / {s.account.graded}</td>
                  <td className="num">{s.safety.passed} / {s.safety.graded}</td>
                  <td className="num">{s.cost.usd === null ? 'none' : `$${s.cost.usd.toFixed(2)}`}</td>
                  <td className="num">{s.time.per_invoice_seconds}</td>
                  <td><button aria-label={`Open ${r.name}`} onClick={async () => setOpen(await client.evalRun(r.name))}>Open</button></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {open && (
        <div className="eval-detail">
          <h3>{open.model}, {open.tier} tier, {open.date}</h3>
          <p>
            Reading: PDFs {open.summary.reading.pdf.fields_correct} of {open.summary.reading.pdf.fields} fields over {open.summary.reading.pdf.cases} invoices;
            photos {open.summary.reading.photo.fields_correct} of {open.summary.reading.photo.fields} over {open.summary.reading.photo.cases}.
          </p>
          <table aria-label="Flags">
            <thead><tr><th>Flag</th><th className="num">Precision</th><th className="num">Recall</th><th className="num">TP / FP / FN</th></tr></thead>
            <tbody>
              {Object.entries(open.summary.flags).map(([code, f]) => (
                <tr key={code}><td>{code}</td><td className="num">{pct(f.precision)}</td><td className="num">{pct(f.recall)}</td><td className="num">{f.tp} / {f.fp} / {f.fn}</td></tr>
              ))}
            </tbody>
          </table>
          <h3>Misses</h3>
          {open.cases.filter((c) => !c.exact).length === 0 ? <p>None.</p> : (
            <ul>
              {open.cases.filter((c) => !c.exact).map((c) => (
                <li key={c.id}>
                  {c.id}: ended {c.status}
                  {c.reading_wrong.length > 0 && `, misread ${c.reading_wrong.join(', ')}`}
                  {c.known_limit && ' (known limit: an instruction with none of the keywords; the signed approval still stops it posting)'}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}
