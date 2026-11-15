import { type Run } from './api'
import { outcome, problemImpact, problemLabel } from './bills'
import { lookupInput, toolLabel } from './system-map'

// How this bill was handled, open on every bill page: what Claude read with the line each value came from and what
// code found when it looked for that line in the PDF, what the checks found, the account check, each lookup the
// agent made with its input and a one-line result (from the run itself: the API's run view), the suggested next
// step, and what the run cost. Nothing here is worked out by the page; it shows the run. The flag details and the
// account's reason are on the page just above, so the trace does not repeat them.

const FIELD: Record<string, string> = {
  vendor_name: 'Vendor',
  vendor_tax_id: 'Tax id',
  number: 'Invoice',
  date: 'Date',
  po: 'PO',
  remit_bank: 'Bank',
  remit_account_last4: 'Account',
  subtotal: 'Subtotal',
  tax: 'Tax',
  total: 'Total',
}
const CHECK: Record<string, string> = { ok: 'found in the PDF', missing: 'NOT found in the PDF', not_checked: 'photo: check by eye' }
// Fields code does not look for in the PDF: what the check that covers each one found (rules.py). A flag means
// that check failed. On a copy already paid, or from a vendor not set up, the rules skip the bank comparison, so the
// trace says it was not compared rather than claiming a match.
type Found = { text: string; tone: 'ok' | 'bad' | 'muted' }
function otherCheck(field: string, codes: Set<string>): Found | null {
  if (field === 'vendor_name')
    return codes.has('VENDOR_NOT_FOUND') ? { text: 'not in the vendor records', tone: 'bad' } : { text: 'found in the vendor records', tone: 'ok' }
  if (field === 'remit_bank') {
    if (codes.has('BANK_CHANGED')) return { text: 'differs from the bank details on file', tone: 'bad' }
    if (codes.has('VENDOR_NOT_FOUND')) return { text: 'no vendor on file to compare with', tone: 'muted' }
    if (codes.has('DUPLICATE')) return { text: 'not compared: already paid', tone: 'muted' }
    return { text: 'matches the bank details on file', tone: 'ok' }
  }
  if (field === 'subtotal' || field === 'tax')
    return codes.has('TOTALS_MISMATCH') ? { text: 'does not add up', tone: 'bad' } : { text: 'adds up with the lines', tone: 'ok' }
  return null
}

function checkCell(field: string, sourceCheck: string | undefined, codes: Set<string>): Found {
  if (sourceCheck === 'missing') return { text: CHECK.missing, tone: 'bad' }
  if (sourceCheck && CHECK[sourceCheck]) return { text: CHECK[sourceCheck], tone: sourceCheck === 'ok' ? 'ok' : 'muted' }
  return otherCheck(field, codes) ?? { text: '', tone: 'muted' }
}

export function BillTrace({ run }: { run: Run }) {
  const x = run.extraction as (Record<string, unknown> & { sources?: Record<string, string> }) | null
  const sources = Object.entries(x?.sources ?? {})
  const flags = run.pause?.flags ?? run.flags ?? []
  const codes = new Set(flags.map((f) => f.code))
  const lookups = run.lookups ?? []
  const account = run.pause?.account_suggestion
  const m = run.metrics
  const next = run.next_step?.action ?? (run.paused && flags.length === 0 ? 'one click from a person: every check passed' : run.paused ? null : outcome(run))
  return (
    <section className="trace" aria-label="How this bill was handled">
      <h3>How this bill was handled</h3>
      <ol className="trace-steps">
        <li>
          <b>Read by Claude, each value with the line it came from</b>
          {sources.length ? (
            <table className="trace-read">
              <tbody>
                {sources.map(([k, quote]) => {
                  const found = checkCell(k, run.source_checks?.[k], codes)
                  return (
                    <tr key={k}>
                      <th>{FIELD[k] ?? k}</th>
                      <td>{String(x?.[k] ?? '')}</td>
                      <td className="quote">{quote}</td>
                      <td className={'check ' + found.tone}>{found.text}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          ) : (
            <p className="fine">No source lines came back with this reading.</p>
          )}
        </li>
        <li>
          <b>The checks, in code</b>
          {flags.length ? (
            <ul>
              {flags.map((f) => (
                <li key={f.code}>
                  {problemLabel(f.code)}
                  {problemImpact(f, run.pause?.total ?? x?.total as string ?? '0') ? `: ${problemImpact(f, run.pause?.total ?? (x?.total as string) ?? '0')}` : ''}
                </li>
              ))}
            </ul>
          ) : (
            <p>Every check passed.</p>
          )}
        </li>
        {account && (
          <li>
            <b>The account</b>
            <p>
              Claude suggested {account.suggested ?? 'none'}; code checked it: {account.check}
              {account.account ? `, so ${account.account} is proposed` : ''}.
            </p>
          </li>
        )}
        <li>
          <b>Claude's lookups, read-only</b>
          {lookups.length ? (
            <ul>
              {lookups.map((l, i) => {
                const input = lookupInput(l.input)
                return (
                  <li key={i} className={l.ok ? '' : 'bad'}>
                    {toolLabel(l.tool)}
                    {input ? ` (${input})` : ''}: {l.result}
                  </li>
                )
              })}
            </ul>
          ) : (
            <p>{flags.length ? 'No lookups were made.' : 'No lookups: nothing needed looking into.'}</p>
          )}
        </li>
        {next && (
          <li>
            <b>{run.paused ? 'The suggested next step' : 'What happened'}</b>
            <p>{next.charAt(0).toUpperCase() + next.slice(1)}.</p>
          </li>
        )}
        {m && (
          <li>
            <b>What it cost</b>
            <p>
              {m.model_calls} model calls{m.cost_usd !== null ? `, $${m.cost_usd.toFixed(4)} at API list prices` : ', scripted: no model, no cost'}
              {run.seconds !== null && run.seconds !== undefined ? `, ${run.seconds} s for the recorded run` : ''}.
            </p>
          </li>
        )}
      </ol>
    </section>
  )
}
