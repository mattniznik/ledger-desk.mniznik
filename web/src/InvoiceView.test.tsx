import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { ApiError, type Client, type Run } from './api'
import { InvoiceView } from './InvoiceView'
import { useFeed } from './map-feed'

beforeAll(() => {
  // jsdom has no object URLs; the view shows the fetched document through one
  URL.createObjectURL = vi.fn(() => 'blob:doc')
  URL.revokeObjectURL = vi.fn()
})

function run08(overrides: Partial<Run> = {}): Run {
  return {
    run_id: 'r-08', sample: '08', invoice_ref: '08-abc', mode: 'replay', model: 'claude-opus-5-5', status: 'exception', paused: true,
    reason: '', entry_id: null, seconds: 22.66,
    metrics: { model_calls: 4, input_tokens: 8, cache_write_tokens: 9000, cache_read_tokens: 4000, output_tokens: 1500, cost_usd: 0.11 },
    extraction: { vendor_name: 'Espresso Repair Service', number: 'REP-3307', date: '2026-11-04', total: '860.00', po: null, remit_bank: 'Example Bank', remit_account_last4: '9921', lines: [{ description: 'Group head rebuild, labor and parts', quantity: '1', unit_price: '860.00', amount: '860.00' }] },
    source_checks: { number: 'ok', date: 'ok', total: 'ok', remit_account_last4: 'ok' },
    email_draft: { subject: 'Invoice REP-3307: please confirm bank details', body: 'Hello, could you confirm the account ending 9921?' },
    due_date: '2026-11-04', mirror: null,
    pause: {
      invoice_ref: '08-abc', status: 'exception', approver: 'controller', controller_only: true, total: '860.00',
      flags: [{ code: 'BANK_CHANGED', detail: 'remit-to account ending 9921, vendor master ending 4417', amount: null, quantity: null }],
      explanation: 'The invoice asks for payment to an account ending 9921; the vendor record has 4417.',
      account_suggestion: { account: '6300', suggested: '6300', check: 'ok', source: 'suggested', reason: 'A repair, not a new asset.' },
      proposal: { lines: [{ account: '6300', debit: '860.00', credit: '0.00' }, { account: '2000', debit: '0.00', credit: '860.00' }] },
    },
    ...overrides,
  } as Run
}

function fakeClient(run: Run, decide?: Client['decide']): Client {
  return {
    run: vi.fn(async () => run),
    document: vi.fn(async () => new Blob(['%PDF'], { type: 'application/pdf' })),
    decide: decide ?? vi.fn(async () => ({ ...run, status: 'posted', paused: false, entry_id: 41 })),
  } as unknown as Client
}

const BANK_STEP = {
  code: 'BANK_CHANGED', decision: 'hold' as const, action: 'Hold until the new bank account is confirmed',
  why: 'The bill asks to be paid into a different bank account from the one on file.',
  then: 'The controller calls Espresso Repair Service on the number already in your vendor records.',
  reason: 'Bank change: on hold until confirmed by phone on the number on file', also: ['Billed $200.00 above the prices agreed on PO-1124.'],
}

describe('the invoice view', () => {
  it('shows what was read and checked, the flags, the explanation, the suggestion and the entry', async () => {
    render(<InvoiceView client={fakeClient(run08())} runId="r-08" onBack={() => {}} />)
    // was findByText('BANK_CHANGED'): the screen now says what the code means (2026-11-14, business wording)
    expect(await screen.findByText('Asks to be paid into a new bank account')).toBeInTheDocument()
    expect(screen.getByText(/vendor master ending 4417/)).toBeInTheDocument()
    expect(screen.getByText(/the vendor record has 4417/)).toBeInTheDocument()
    expect(screen.getByText(/please confirm bank details/)).toBeInTheDocument()
    expect(screen.getByText(/A repair, not a new asset/)).toBeInTheDocument()
    expect(screen.getAllByText('$860.00').length).toBeGreaterThan(0)
    expect(screen.getByText('REP-3307')).toBeInTheDocument()
    expect(screen.getByTitle('invoice document')).toHaveAttribute('data', 'blob:doc')
    expect(screen.getByText(/Replay of a real Claude run/)).toBeInTheDocument()
  })

  it('asks for the phone check only when the pause says controller only', async () => {
    const { unmount } = render(<InvoiceView client={fakeClient(run08())} runId="r-08" onBack={() => {}} />)
    expect(await screen.findByLabelText(/called the vendor on the number already on file/i)).toBeInTheDocument()
    unmount()
    const plain = run08({ pause: { ...run08().pause!, controller_only: false, approver: 'clerk', flags: [], status: 'ready' } })
    render(<InvoiceView client={fakeClient(plain)} runId="r-08" onBack={() => {}} />)
    await screen.findByText('REP-3307')
    expect(screen.queryByLabelText(/called the vendor/i)).not.toBeInTheDocument()
  })

  it("shows a refusal exactly as the API wrote it and keeps the invoice waiting", async () => {
    const decide = vi.fn(async () => { throw new ApiError(403, 'only the controller may approve a bank change') })
    render(<InvoiceView client={fakeClient(run08(), decide as unknown as Client['decide'])} runId="r-08" onBack={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('403: only the controller may approve a bank change')
    expect(decide).toHaveBeenCalledWith('r-08', { role: 'clerk', decision: 'approve', reason: '', phone_confirmed: false })
    expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument()
  })

  it('sends the role, the reason and the phone box, and shows the posted entry', async () => {
    const client = fakeClient(run08())
    render(<InvoiceView client={client} runId="r-08" onBack={() => {}} />)
    fireEvent.click(await screen.findByLabelText('Controller'))
    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: 'called 4417 number on file' } })
    fireEvent.click(screen.getByLabelText(/called the vendor on the number already on file/i))
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    // was /posted as ERP entry 41/: "ERP" means nothing to the bookkeeper (2026-11-14)
    expect(await screen.findByText(/Booked as entry 41/)).toBeInTheDocument()
    expect(client.decide).toHaveBeenCalledWith('r-08', { role: 'controller', decision: 'approve', reason: 'called 4417 number on file', phone_confirmed: true })
  })

  it('puts the verdict first, in plain words, with the due date and the full draft email', async () => {
    render(<InvoiceView client={fakeClient(run08())} runId="r-08" onBack={() => {}} />)
    expect(await screen.findByText('Needs a look: Asks to be paid into a new bank account')).toBeInTheDocument()
    expect(screen.getByText('Nov 4, 2026')).toBeInTheDocument()
    expect(screen.getByText(/could you confirm the account ending 9921/)).toBeInTheDocument()
    expect(screen.getByText(/not sent/i)).toBeInTheDocument()
  })

  it('says a clean bill is ready to approve', async () => {
    const clean = run08({ pause: { ...run08().pause!, controller_only: false, approver: 'clerk', flags: [], status: 'ready' } })
    render(<InvoiceView client={fakeClient(clean)} runId="r-08" onBack={() => {}} />)
    expect(await screen.findByText('Ready to approve: every check passed')).toBeInTheDocument()
  })

  it('after approval, says the bill is booked and which QuickBooks bill it became', async () => {
    const posted = { ...run08(), status: 'posted', paused: false, entry_id: 41, mirror: { status: 'mirrored', entity: 'Bill', id: '147', doc_number: 'REP-3307', created: true, total: 860 } } as Run
    const decide = vi.fn(async () => posted)
    render(<InvoiceView client={fakeClient(run08(), decide as unknown as Client['decide'])} runId="r-08" onBack={() => {}} />)
    fireEvent.click(await screen.findByLabelText('Controller'))
    fireEvent.click(screen.getByLabelText(/called the vendor on the number already on file/i))
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    expect(await screen.findByText('Approved · in QuickBooks as Bill 147')).toBeInTheDocument()
    expect(screen.getByText(/Booked as entry 41/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
  })

  it('shows a QuickBooks failure as it is, with the bill still booked', async () => {
    const failed = { ...run08(), status: 'posted', paused: false, entry_id: 41, mirror: { status: 'failed', error: 'QuickBooksError: 503 Service Unavailable' } } as Run
    render(<InvoiceView client={fakeClient(failed)} runId="r-08" onBack={() => {}} />)
    expect(await screen.findByText('Approved and booked · not in QuickBooks: QuickBooksError: 503 Service Unavailable')).toBeInTheDocument()
    expect(screen.getByText(/Booked as entry 41/)).toBeInTheDocument()
  })

  it('says nobody can approve yet when there is no entry to book', async () => {
    const noEntry = run08({ pause: { ...run08().pause!, controller_only: false, approver: 'clerk', proposal: { lines: [] },
      flags: [{ code: 'VENDOR_NOT_FOUND', detail: 'not in the vendor master', amount: null, quantity: null }] } })
    render(<InvoiceView client={fakeClient(noEntry)} runId="r-08" onBack={() => {}} />)
    expect(await screen.findByText(/Nobody can approve it yet: there is no entry to book/)).toBeInTheDocument()
  })

  it('says what Hold did', async () => {
    const decide = vi.fn(async () => run08())
    render(<InvoiceView client={fakeClient(run08(), decide as unknown as Client['decide'])} runId="r-08" onBack={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Hold' }))
    expect(await screen.findByText(/On hold: it stays under Needs a look/)).toBeInTheDocument()
  })

  it('says a failed booking failed, never "booked"', async () => {
    const failed = run08({ status: 'post_failed', paused: false, entry_id: null })
    render(<InvoiceView client={fakeClient(failed)} runId="r-08" onBack={() => {}} />)
    expect(await screen.findByText('Approved, but booking failed: nothing was posted')).toBeInTheDocument()
    expect(screen.queryByText(/Booked as entry/)).not.toBeInTheDocument()
  })

  it('does not promise QuickBooks when it may not be connected', async () => {
    render(<InvoiceView client={fakeClient(run08())} runId="r-08" onBack={() => {}} />)
    expect(await screen.findByText(/adds it to QuickBooks when QuickBooks is connected/)).toBeInTheDocument()
  })

  it('leads a problem bill with the suggested next step, and one click sends that decision and its reason', async () => {
    const run = run08({ next_step: BANK_STEP, held: false })
    const decide = vi.fn(async () => ({ ...run, held: true }))
    render(<InvoiceView client={fakeClient(run, decide)} runId="r-08" onBack={() => {}} />)
    const box = await screen.findByRole('region', { name: 'Suggested next step' })
    expect(box).toHaveTextContent('different bank account from the one on file')
    expect(box).toHaveTextContent('number already in your vendor records')
    expect(box).toHaveTextContent('Also: Billed $200.00 above the prices agreed on PO-1124.')
    fireEvent.click(screen.getByRole('button', { name: 'Hold until the new bank account is confirmed' }))
    await screen.findByText(/On hold: it stays under Needs a look/)
    expect(decide).toHaveBeenCalledWith('r-08', { role: 'clerk', decision: 'hold', reason: BANK_STEP.reason, phone_confirmed: false })
    expect(screen.queryByRole('button', { name: 'Hold until the new bank account is confirmed' })).not.toBeInTheDocument()
  })

  it('a bill already on hold says what it is waiting for and offers no second hold', async () => {
    render(<InvoiceView client={fakeClient(run08({ next_step: BANK_STEP, held: true }))} runId="r-08" onBack={() => {}} />)
    const box = await screen.findByRole('region', { name: 'Suggested next step' })
    expect(box).toHaveTextContent('On hold. Next: The controller calls Espresso Repair Service')
    expect(screen.queryByRole('button', { name: BANK_STEP.action })).not.toBeInTheDocument()
  })

  it('offers a reject when the step is a reject', async () => {
    const dup = { ...BANK_STEP, code: 'DUPLICATE', decision: 'reject' as const, action: 'Reject as already paid', reason: 'Duplicate: DAI-5521 already paid on Oct 14, 2026', also: [] }
    const run = run08({ next_step: dup, held: false })
    const decide = vi.fn(async () => ({ ...run, status: 'rejected', paused: false, pause: null, next_step: null }))
    render(<InvoiceView client={fakeClient(run, decide)} runId="r-08" onBack={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Reject as already paid' }))
    await screen.findByText('Rejected')
    expect(decide).toHaveBeenCalledWith('r-08', { role: 'clerk', decision: 'reject', reason: dup.reason, phone_confirmed: false })
  })

  it('shows no suggested step on a clean bill', async () => {
    const plain = run08({ next_step: null, pause: { ...run08().pause!, controller_only: false, approver: 'clerk', flags: [], status: 'ready' } })
    render(<InvoiceView client={fakeClient(plain)} runId="r-08" onBack={() => {}} />)
    await screen.findByText('Ready to approve: every check passed')
    expect(screen.queryByRole('region', { name: 'Suggested next step' })).not.toBeInTheDocument()
  })

  it("labels the AI's work as the AI's: its findings and its draft email", async () => {
    render(<InvoiceView client={fakeClient(run08())} runId="r-08" onBack={() => {}} />)
    expect(await screen.findByText('What the AI found:')).toBeInTheDocument()
    expect(screen.getByText('Email to the vendor, drafted by the AI (not sent):')).toBeInTheDocument()
  })

  it('a one-click hold never records the phone check, even with the box ticked', async () => {
    const run = run08({ next_step: BANK_STEP, held: false })
    const decide = vi.fn(async () => ({ ...run, held: true }))
    render(<InvoiceView client={fakeClient(run, decide)} runId="r-08" onBack={() => {}} />)
    fireEvent.click(await screen.findByLabelText(/called the vendor on the number already on file/i))
    fireEvent.click(screen.getByRole('button', { name: BANK_STEP.action }))
    await screen.findByText(/On hold: it stays under Needs a look/)
    expect(decide).toHaveBeenCalledWith('r-08', { role: 'clerk', decision: 'hold', reason: BANK_STEP.reason, phone_confirmed: false })
  })

  it('an approve step sends the approval with its reason', async () => {
    const credit = { ...BANK_STEP, code: 'PRICE_VARIANCE', decision: 'approve' as const, action: 'Approve against credit CM-PKG-0412', reason: 'Overcharge of $200.00 settled by credit memo CM-PKG-0412', also: [] }
    const run = run08({ next_step: credit, held: false })
    const decide = vi.fn(async () => ({ ...run, status: 'posted', paused: false, pause: null, next_step: null, entry_id: 42 }))
    render(<InvoiceView client={fakeClient(run, decide)} runId="r-08" onBack={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Approve against credit CM-PKG-0412' }))
    await screen.findByText(/Booked as entry 42/)
    expect(decide).toHaveBeenCalledWith('r-08', { role: 'clerk', decision: 'approve', reason: credit.reason, phone_confirmed: false })
  })
})

function FeedProbe() {
  const f = useFeed()
  return <p data-testid="feed">{f ? `${f.mode} | ${f.title} | ${f.events.map((e) => e.type).join(' ')}` : 'none'}</p>
}

describe('the bill on the system map', () => {
  it('hands the open bill to the map, and its decision after it', async () => {
    const run = run08({ next_step: BANK_STEP, held: false, lookups: [{ tool: 'get_vendor', input: { tax_id: '00-0000005' }, result: 'Espresso Repair Service, Example Bank account ending 4417', ok: true }] })
    const decide = vi.fn(async () => ({ ...run, held: true }))
    render(<><InvoiceView client={fakeClient(run, decide)} runId="r-08" onBack={() => {}} /><FeedProbe /></>)
    const feed = await screen.findByTestId('feed')
    await vi.waitFor(() => expect(feed).toHaveTextContent('desk | Espresso Repair Service REP-3307 | bill read sources checks account lookup next pause'))
    fireEvent.click(screen.getByRole('button', { name: BANK_STEP.action }))
    await vi.waitFor(() => expect(feed).toHaveTextContent('pause decision held'))
  })
})

describe('how this bill was handled', () => {
  it('is open on the page: what was read with its source, the checks, each lookup, the next step and the cost', async () => {
    const base = run08()
    const run = run08({
      next_step: BANK_STEP,
      held: false,
      extraction: { ...base.extraction!, sources: { number: 'No. REP-3307', total: 'Total due $860.00', remit_account_last4: 'Remit to: Example Bank, account ending 9921' } },
      lookups: [
        { tool: 'get_vendor', input: { tax_id: '00-0000005' }, result: 'Espresso Repair Service, Example Bank account ending 4417', ok: true },
        { tool: 'draft_vendor_email', input: { subject: 'REP-3307 bank details' }, result: 'saved for a person, not sent', ok: true },
      ],
    })
    render(<InvoiceView client={fakeClient(run)} runId="r-08" onBack={() => {}} />)
    const trace = await screen.findByRole('region', { name: 'How this bill was handled' })
    expect(within(trace).getByText('Remit to: Example Bank, account ending 9921')).toBeInTheDocument()
    expect(within(trace).getAllByText('found in the PDF').length).toBe(3)
    expect(trace).toHaveTextContent('Asks to be paid into a new bank account')
    expect(trace).toHaveTextContent('Vendor record (tax id 00-0000005): Espresso Repair Service, Example Bank account ending 4417')
    expect(trace).toHaveTextContent('Draft email: saved for a person, not sent')
    expect(trace).toHaveTextContent('Hold until the new bank account is confirmed')
    expect(trace).toHaveTextContent('4 model calls')
  })

  it('says when there were no lookups and every check passed', async () => {
    const plain = run08({ next_step: null, lookups: [], pause: { ...run08().pause!, controller_only: false, approver: 'clerk', flags: [], status: 'ready' } })
    render(<InvoiceView client={fakeClient(plain)} runId="r-08" onBack={() => {}} />)
    const trace = await screen.findByRole('region', { name: 'How this bill was handled' })
    expect(trace).toHaveTextContent('Every check passed')
    expect(trace).toHaveTextContent('No lookups: nothing needed looking into')
  })

  it("says what each field's check found, and never shows a failed check as passed", async () => {
    const base = run08()
    const sources = { vendor_name: 'Espresso Repair Service', remit_bank: 'Remit to: Example Bank, account ending 9921', subtotal: 'Subtotal $860.00' }
    const flagged = run08({ next_step: BANK_STEP, held: false, extraction: { ...base.extraction!, sources } })
    const { unmount } = render(<InvoiceView client={fakeClient(flagged)} runId="r-08" onBack={() => {}} />)
    const trace = await screen.findByRole('region', { name: 'How this bill was handled' })
    const bank = within(trace).getByText('differs from the bank details on file')
    expect(bank).toHaveClass('bad')
    expect(within(trace).getByText('found in the vendor records')).not.toHaveClass('bad')
    expect(within(trace).getByText('adds up with the lines')).not.toHaveClass('bad')
    expect(within(trace).queryByText('matches the bank details on file')).not.toBeInTheDocument()
    unmount()

    // an already-paid copy: the rules skip the bank comparison, so the trace must not claim it matched
    const dup = run08({ next_step: null, extraction: { ...base.extraction!, sources },
      pause: { ...base.pause!, controller_only: false, flags: [{ code: 'DUPLICATE', detail: 'DAI-5521 was already paid', amount: null, quantity: null }] } })
    render(<InvoiceView client={fakeClient(dup)} runId="r-08" onBack={() => {}} />)
    const t2 = await screen.findByRole('region', { name: 'How this bill was handled' })
    expect(within(t2).getByText('not compared: already paid')).not.toHaveClass('bad')
    expect(within(t2).queryByText('matches the bank details on file')).not.toBeInTheDocument()
  })
})
