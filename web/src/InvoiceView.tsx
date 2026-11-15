import { useEffect, useState } from 'react'
import { ApiError, type Client, type Decision, type Run, usd } from './api'
import { dueLabel, outcome, problemImpact, problemLabel } from './bills'
import { BillTrace } from './BillTrace'
import { MetricsFooter } from './MetricsFooter'
import { publish } from './map-feed'
import { eventsFromRun } from './system-map'

type Props = { client: Client; runId: string; onBack: () => void }

const CHECK_LABEL: Record<string, string> = { ok: 'found in the PDF', missing: 'NOT found in the PDF', not_checked: 'photo: check by eye' }

// One bill: the verdict in plain words first, then the document beside what was read from it, what
// the checks and the AI found, how it will be booked, and the decision. The rules (who may approve what) are enforced by the API; this page shows its
// answer as written, so a 403 or 400 reads exactly as the API said it.
export function InvoiceView({ client, runId, onBack }: Props) {
  const [run, setRun] = useState<Run | null>(null)
  const [docUrl, setDocUrl] = useState<string | null>(null)
  const [docType, setDocType] = useState('')
  const [role, setRole] = useState<Decision['role']>('clerk')
  const [reason, setReason] = useState('')
  const [phone, setPhone] = useState(false)
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  const [heldNow, setHeldNow] = useState(false)

  // the system map follows the bill that is open, and its decision when it is made
  useEffect(() => {
    if (!run) return
    const title = `${run.extraction?.vendor_name ?? ''} ${run.extraction?.number ?? ''}`.trim() || run.sample
    publish({ id: `desk-${run.run_id}`, title, mode: 'desk', events: eventsFromRun(run) })
  }, [run])

  useEffect(() => {
    let url: string | null = null
    client.run(runId).then(setRun).catch((e) => setError(String(e.message ?? e)))
    client.document(runId).then((blob) => {
      url = URL.createObjectURL(blob)
      setDocType(blob.type)
      setDocUrl(url)
    }).catch(() => {})
    return () => { if (url) URL.revokeObjectURL(url) }
  }, [client, runId])

  async function decide(decision: Decision['decision'], why = reason) {
    setSending(true)
    setError('')
    try {
      // the phone box is part of an approval only: a hold or a reject never records a phone check
      setRun(await client.decide(runId, { role, decision, reason: why, phone_confirmed: decision === 'approve' ? phone : false }))
      setHeldNow(decision === 'hold') // a hold leaves the run waiting, so the page would otherwise look unchanged
    } catch (e) {
      setError(e instanceof ApiError ? `${e.status}: ${e.message}` : String(e))
    } finally {
      setSending(false)
    }
  }

  if (!run) return <p>{error || 'Loading…'}</p>
  const pause = run.pause
  const e = run.extraction
  const verdict = run.paused && pause
    ? pause.flags.length > 0
      ? `Needs a look: ${pause.flags.map((f) => problemLabel(f.code)).join('; ')}`
      : 'Ready to approve: every check passed'
    : outcome(run)

  return (
    <section className="invoice">
      <button onClick={onBack}>Back to the bills</button>
      <p className={`verdict ${run.paused ? (pause?.flags.length ? 'needs' : 'ready') : 'done'}`}>{verdict}</p>
      <div className="split">
        <div className="doc">
          {docUrl && (docType.startsWith('image/')
            ? <img src={docUrl} alt="invoice document" title="invoice document" />
            : <object data={docUrl} type="application/pdf" title="invoice document" />)}
        </div>
        <div className="facts">
          {e && (
            <>
              <h2>{e.vendor_name}</h2>
              <table>
                <tbody>
                  <tr><th>Invoice</th><td>{e.number}</td><td className="check">{CHECK_LABEL[run.source_checks.number] ?? ''}</td></tr>
                  <tr><th>Date</th><td>{e.date}</td><td className="check">{CHECK_LABEL[run.source_checks.date] ?? ''}</td></tr>
                  <tr><th>Total</th><td>{usd(e.total)}</td><td className="check">{CHECK_LABEL[run.source_checks.total] ?? ''}</td></tr>
                  {Number(e.total) < 0
                    ? <tr><th>Due</th><td colSpan={2}>a credit: it reduces what is owed</td></tr>
                    : run.due_date && <tr><th>Due</th><td>{dueLabel(run.due_date)}</td><td className="check">from the vendor's terms</td></tr>}
                  <tr><th>PO</th><td>{e.po ?? 'none'}</td><td className="check">{CHECK_LABEL[run.source_checks.po] ?? ''}</td></tr>
                  <tr><th>Pay to</th><td>{e.remit_bank}, account ending {e.remit_account_last4}</td><td className="check">{CHECK_LABEL[run.source_checks.remit_account_last4] ?? ''}</td></tr>
                </tbody>
              </table>
            </>
          )}

          {run.entry_id && <p className="booked">Booked as entry {run.entry_id} in the company's books.</p>}

          {run.paused && run.next_step && (
            // What a finance team would do about it (playbook.py), first, so the problem arrives as a
            // decision ready to make. The button sends that decision and its reason through the same
            // rules as the form below.
            <section className="next-step" aria-label="Suggested next step">
              <h3>Suggested next step</h3>
              <p>{run.next_step.why}</p>
              {run.held || heldNow
                ? <p><strong>On hold.</strong> Next: {run.next_step.then}</p>
                : <p>{run.next_step.then}</p>}
              {run.next_step.also.length > 0 && <p className="fine">Also: {run.next_step.also.join(' ')}</p>}
              {!(run.held || heldNow) && (
                <button className="primary" disabled={sending} onClick={() => decide(run.next_step!.decision, run.next_step!.reason)}>
                  {run.next_step.action}
                </button>
              )}
            </section>
          )}

          {pause && pause.flags.length > 0 && (
            <div className="flags">
              <h3>What the checks found</h3>
              {pause.flags.map((f) => (
                <p key={f.code}>
                  <span className="flag" title={f.code}>{problemLabel(f.code)}</span>
                  {problemImpact(f, pause.total) && <strong className="impact">{problemImpact(f, pause.total)}</strong>}
                  <span className="detail">{f.detail}</span>
                </p>
              ))}
            </div>
          )}
          {pause?.explanation && <blockquote className="agent"><strong>What the AI found:</strong> {pause.explanation}</blockquote>}
          {run.email_draft && (
            <details className="draft">
              <summary><span>Email to the vendor, drafted by the AI (not sent):</span> <em>{run.email_draft.subject}</em></summary>
              <pre>{run.email_draft.body}</pre>
            </details>
          )}

          {pause?.account_suggestion && (
            <p className="suggestion">
              Account: Claude suggested <strong>{pause.account_suggestion.suggested ?? 'none'}</strong>, check{' '}
              <strong>{pause.account_suggestion.check}</strong>
              {pause.account_suggestion.account && <> → proposed <strong>{pause.account_suggestion.account}</strong></>}.{' '}
              {pause.account_suggestion.reason}
            </p>
          )}

          {pause && pause.proposal.lines.length > 0 && <h3>How it will be booked</h3>}
          {pause && pause.proposal.lines.length > 0 && (
            <table className="entry">
              <thead><tr><th>Account</th><th className="num">Debit</th><th className="num">Credit</th></tr></thead>
              <tbody>
                {pause.proposal.lines.map((l, i) => (
                  <tr key={i}><td>{l.account}</td><td className="num">{l.debit !== '0.00' ? usd(l.debit) : ''}</td><td className="num">{l.credit !== '0.00' ? usd(l.credit) : ''}</td></tr>
                ))}
              </tbody>
            </table>
          )}
          {pause && pause.proposal.lines.length === 0 && <p>{pause.proposal.note ?? 'No entry proposed.'}</p>}

          {run.paused && pause && (
            <form className="decide" onSubmit={(ev) => ev.preventDefault()}>
              {pause.proposal.lines.length === 0 ? (
                <p>Nobody can approve it yet: there is no entry to book. The vendor has to be set up and the bill coded first.</p>
              ) : (
                <p>Who can approve: <strong>{pause.approver === 'controller' ? 'the controller' : 'a clerk or the controller'}</strong>{pause.controller_only ? ' (a bank change: controller only, after a phone check)' : ''}</p>
              )}
              <fieldset>
                <legend>Signed in as (demo: pick a role)</legend>
                <label><input type="radio" name="role" checked={role === 'clerk'} onChange={() => setRole('clerk')} /> Clerk</label>
                <label><input type="radio" name="role" checked={role === 'controller'} onChange={() => setRole('controller')} /> Controller</label>
              </fieldset>
              <label className="block">
                Reason {pause.status === 'exception' ? '(required to approve with a flag open)' : '(optional)'}
                <textarea value={reason} onChange={(ev) => setReason(ev.target.value)} rows={2} />
              </label>
              {pause.controller_only && (
                <label className="block">
                  <input type="checkbox" checked={phone} onChange={(ev) => setPhone(ev.target.checked)} /> I called the vendor on the number already on file and they confirmed the bank account
                </label>
              )}
              <div className="buttons">
                <button disabled={sending} onClick={() => decide('approve')}>Approve</button>
                <button disabled={sending} onClick={() => decide('hold')}>Hold</button>
                <button disabled={sending} onClick={() => decide('reject')}>Reject</button>
              </div>
              {heldNow && <p className="booked" role="status">On hold: it stays under Needs a look until someone approves or rejects it.</p>}
              <p className="fine">Approve books it, and adds it to QuickBooks when QuickBooks is connected. Hold keeps it waiting. Reject closes it without paying.</p>
            </form>
          )}
          {error && <p role="alert" className="error">{error}</p>}
        </div>
      </div>
      <BillTrace run={run} />
      <MetricsFooter run={run} />
    </section>
  )
}
