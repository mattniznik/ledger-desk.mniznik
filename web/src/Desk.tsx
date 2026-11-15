import { useMemo, useRef, useState } from 'react'
import { type Client, createClient } from './api'
import { AuditView } from './AuditView'
import { HowItWorks } from './HowItWorks'
import { Inbox } from './Inbox'
import { InvoiceView } from './InvoiceView'
import { TOUR } from './tour'
import { Walkthrough } from './Walkthrough'
import './desk.css'

// The bill desk: the queue, a bill, the walkthrough, the audit trail and How it works. Every layout embeds it as its
// demo (rich/, simple/); the layout carries the page's own heading, so the desk opens on its tabs.
export function Desk({ client: given }: { client?: Client } = {}) {
  const client = useMemo(() => given ?? createClient(), [given])
  const [openRun, setOpenRun] = useState<string | null>(null)
  const [tab, setTab] = useState<'bills' | 'audit' | 'how'>('bills')
  const [tour, setTour] = useState<number | null>(null)
  const [tourNote, setTourNote] = useState('')
  const tourRequest = useRef(0) // a quick Next twice: only the newest step opens its bill
  const [visitor, setVisitor] = useState(0) // a new visitor after "Start over": the queue reads fresh bills

  // Anything the visitor opens by hand wins over a walkthrough step still loading its bill
  function open(runId: string | null) {
    tourRequest.current++
    setOpenRun(runId)
  }
  function show(next: 'bills' | 'audit' | 'how') {
    tourRequest.current++
    setTab(next)
    setOpenRun(null)
  }
  function restart() {
    client.reset()
    setVisitor((v) => v + 1)
    goTo(0)
  }

  async function goTo(n: number) {
    const step = TOUR[n]
    const request = ++tourRequest.current
    setTour(n)
    setTourNote('')
    setTab(step.go.tab)
    setOpenRun(null)
    if (!step.go.bill) return
    try {
      const sample = (await client.samples()).find((x) => x.number === step.go.bill)
      if (!sample) throw new Error('it is not among the sample bills')
      // the visitor's run for that bill, or read now if the queue has not got to it yet (one per visitor, api.py)
      const run = await client.startRun(sample.id, 'replay')
      if (request === tourRequest.current) setOpenRun(run.run_id)
    } catch (e) {
      if (request === tourRequest.current) setTourNote(`Could not open ${step.go.bill}: ${e instanceof Error ? e.message : String(e)}`)
    }
  }

  function endTour() {
    tourRequest.current++
    setTour(null)
    setTourNote('')
  }
  return (
    <div className="desk" id="desk">
      <div className="desk-head">
        <p className="desk-brand">Coffee Roastery <span className="demo-badge">fictional company, demo data</span></p>
        <nav className="desk-tabs" aria-label="Desk">
          <button className={tab === 'bills' ? 'active' : ''} aria-pressed={tab === 'bills'} onClick={() => show('bills')}>Bills</button>
          <button className={tab === 'audit' ? 'active' : ''} aria-pressed={tab === 'audit'} onClick={() => show('audit')}>Audit trail</button>
          <button className={tab === 'how' ? 'active' : ''} aria-pressed={tab === 'how'} onClick={() => show('how')}>How it works</button>
        </nav>
        {tour === null && (
          <button className="primary tour-start" onClick={() => goTo(0)}>Walk through a morning in accounts payable ({TOUR.length} steps)</button>
        )}
      </div>
      {tour !== null && <Walkthrough step={tour} note={tourNote} onStep={goTo} onExit={endTour} onRestart={restart} />}
      {tab === 'audit' ? (
        <AuditView key={visitor} client={client} />
      ) : tab === 'how' ? (
        <HowItWorks client={client} />
      ) : openRun ? (
        <InvoiceView client={client} runId={openRun} onBack={() => open(null)} />
      ) : (
        <Inbox key={visitor} client={client} onOpen={open} />
      )}
    </div>
  )
}
