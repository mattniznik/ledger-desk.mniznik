import { useCallback, useEffect, useState } from 'react'
import type { AuditEntry, Client, Verify } from './api'

// The visitor's audit log: every step with who did it (a person, the AI, code, the workflow).
// Each row carries the hash of the row before it, so "Verify audit log" re-computes the chain
// and names the first row that no longer checks out. "Edit a row" does what only the database
// owner could do, to show that an edit cannot go unnoticed.
export function AuditView({ client }: { client: Client }) {
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [result, setResult] = useState<Verify | null>(null)
  const [edited, setEdited] = useState<number | null>(null)

  const load = useCallback(() => client.audit().then(setEntries), [client])
  useEffect(() => { load() }, [load])

  async function verify() {
    setResult(await client.verify())
  }

  async function tamper() {
    const r = await client.tamper()
    setEdited(r.edited_id)
    setResult(null)
    await load()
  }

  const bad = result && !result.intact ? result.first_bad_id : null

  return (
    <section className="audit">
      <h2>Audit trail</h2>
      <div className="buttons">
        <button data-audit="verify" onClick={verify}>Verify audit log</button>
        <button className="secondary" data-audit="tamper" onClick={tamper}>Edit a row behind the app's back</button>
      </div>
      {result && (
        <p role="status" className={result.intact ? 'ok' : 'error'}>
          {result.intact ? `Intact: all ${result.rows} rows check out` : `Broken at row ${result.first_bad_id}: its hash no longer matches what was written`}
        </p>
      )}
      {edited !== null && !result && <p className="fine">Row {edited} was edited directly in the database. Now verify.</p>}
      <div className="table-wrap">
      <table>
        <thead>
          <tr><th>#</th><th className="when">When</th><th>Who</th><th>What</th><th className="entity">Invoice</th><th>Hash</th></tr>
        </thead>
        <tbody>
          {entries.map((e) => (
            <tr key={e.id} className={e.id === bad ? 'bad' : undefined}>
              <td>{e.id}</td>
              <td className="when">{new Date(e.at).toLocaleTimeString()}</td>
              <td>{e.actor}</td>
              <td className="action">{e.action}</td>
              <td className="entity">{e.entity.length > 20 ? '' : e.entity}</td>
              <td className="hash">{e.hash.slice(0, 10)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </section>
  )
}
