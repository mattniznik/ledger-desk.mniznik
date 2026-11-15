import { StrictMode } from 'react'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Inbox } from './Inbox'
import type { Client, InvoiceRow, Run, Sample } from './api'

// The bill queue a bookkeeper opens: bills already read, sorted into what needs a look, what is
// ready to approve and what is done, in plain words, with the money at risk added up.
// Replaces the first version's tests (a Run button per invoice and the answer key as a column),
// deliberately: that version did not say who the app was for.

const samples: Sample[] = [
  { id: '08', vendor_name: 'Espresso Repair Service', number: 'REP-3307', total: '860.00', document: 'pdf', what_is_wrong: 'the remit-to account differs from the vendor master', replay: true },
  { id: '09', vendor_name: 'Electric Utility', number: 'UTL-4411', total: '1140.00', document: 'pdf', what_is_wrong: 'nothing; within the usual amount', replay: true },
  { id: '13', vendor_name: 'Roasting Equipment Supplier', number: 'EQP-5502', total: '13423.00', document: 'pdf', what_is_wrong: 'nothing; capital', replay: true },
]

function base(sample: string, number: string, total: string): Run {
  return {
    run_id: `r-${sample}`, sample, invoice_ref: `${sample}-abc`, mode: 'replay', model: 'claude-opus-5-5', status: 'ready', paused: true,
    reason: '', metrics: null, entry_id: null, source_checks: {}, email_draft: null, seconds: null, due_date: null, mirror: null,
    extraction: { vendor_name: '', number, date: '2026-11-01', total, po: null, remit_bank: '', remit_account_last4: '', lines: [] },
    pause: { invoice_ref: `${sample}-abc`, status: 'ready', flags: [], approver: 'clerk', proposal: { lines: [{ account: '6200', debit: total, credit: '0.00' }, { account: '2000', debit: '0.00', credit: total }] }, explanation: '', account_suggestion: null, controller_only: false, total },
    flags: [], held: false, next_step: null, lookups: [],
  }
}

const run08: Run = {
  ...base('08', 'REP-3307', '860.00'), status: 'exception', due_date: '2026-11-04',
  pause: { ...base('08', 'REP-3307', '860.00').pause!, status: 'exception', approver: 'controller', controller_only: true,
    flags: [{ code: 'BANK_CHANGED', detail: 'remit-to account ending 9921, vendor master ending 4417', amount: null, quantity: null }] },
}
const run09: Run = { ...base('09', 'UTL-4411', '1140.00'), due_date: '2026-12-01' }
const run13: Run = {
  ...base('13', 'EQP-5502', '13423.00'), status: 'posted', paused: false, pause: null, entry_id: 41,
  mirror: { status: 'mirrored', entity: 'Bill', id: '146', doc_number: 'EQP-5502', created: true, total: 13423 },
}

function fakeClient(alreadyRead: InvoiceRow[] = [{ id: 1, number: 'EQP-5502', vendor_name: 'Roasting Equipment Supplier', status: 'posted', total: '13423.00', run_id: 'r-13', flags: [] }]): Client {
  const byId: Record<string, Run> = { 'r-13': run13 }
  const bySample: Record<string, Run> = { '08': run08, '09': run09, '13': run13 }
  return {
    samples: vi.fn(async () => samples),
    invoices: vi.fn(async () => alreadyRead),
    run: vi.fn(async (id: string) => byId[id]),
    startRun: vi.fn(async (id: string) => bySample[id]),
  } as unknown as Client
}

async function loaded(client: Client) {
  render(<StrictMode><Inbox client={client} onOpen={() => {}} /></StrictMode>)
  await screen.findByRole('region', { name: /Ready to approve/ })
  await waitFor(() => expect(screen.queryByText(/Reading new bills/)).not.toBeInTheDocument())
}

describe('the bill queue', () => {
  it('reads the bills this session has not seen yet, each once, and leaves the rest alone', async () => {
    const client = fakeClient()
    await loaded(client)
    // StrictMode runs effects twice in development; each sample must still be read once
    expect(client.startRun).toHaveBeenCalledTimes(2)
    expect(client.startRun).toHaveBeenCalledWith('08', 'replay')
    expect(client.startRun).toHaveBeenCalledWith('09', 'replay')
    expect(client.run).toHaveBeenCalledWith('r-13')
  })

  it('sorts bills into needs a look, ready to approve and done, and says what is wrong in plain words', async () => {
    await loaded(fakeClient())
    const needs = screen.getByRole('region', { name: /Needs a look/ })
    expect(within(needs).getByText('Espresso Repair Service')).toBeInTheDocument()
    expect(within(needs).getByText('Asks to be paid into a new bank account')).toBeInTheDocument()
    expect(within(needs).getByText(/\$860\.00 at risk until the bank account is confirmed/)).toBeInTheDocument()
    expect(within(needs).getByText('Controller')).toBeInTheDocument()
    expect(within(needs).queryByText('BANK_CHANGED')).not.toBeInTheDocument()

    const ready = screen.getByRole('region', { name: /Ready to approve/ })
    expect(within(ready).getByText('Electric Utility')).toBeInTheDocument()
    expect(within(ready).getByText('Dec 1, 2026')).toBeInTheDocument()
    expect(within(ready).getByText('$1,140.00')).toBeInTheDocument()

    const done = screen.getByRole('region', { name: /Done/ })
    expect(within(done).getByText('Roasting Equipment Supplier')).toBeInTheDocument()
    expect(within(done).getByText('Approved · in QuickBooks as Bill 146')).toBeInTheDocument()
  })

  it('adds up the money at risk that was caught before paying', async () => {
    await loaded(fakeClient())
    const card = screen.getByRole('group', { name: 'Caught before paying' })
    expect(within(card).getByText('$860.00')).toBeInTheDocument()
    const ready = screen.getByRole('group', { name: 'Ready to approve' })
    expect(within(ready).getByText('1 bill · $1,140.00')).toBeInTheDocument()
  })

  it('keeps the demo answer key out of the way until asked, and says the bills were read by a replay', async () => {
    await loaded(fakeClient())
    expect(screen.queryByText(/remit-to account differs/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /what was planted/i }))
    expect(screen.getByText(/remit-to account differs/)).toBeInTheDocument()
    expect(screen.getByText(/replay of a real Claude run/i)).toBeInTheDocument()
  })

  it('opens a bill for review', async () => {
    const onOpen = vi.fn()
    render(<Inbox client={fakeClient()} onOpen={onOpen} />)
    const needs = await screen.findByRole('region', { name: /Needs a look/ })
    await waitFor(() => expect(within(needs).getByRole('button', { name: 'Review REP-3307' })).toBeEnabled())
    fireEvent.click(within(needs).getByRole('button', { name: 'Review REP-3307' }))
    expect(onOpen).toHaveBeenCalledWith('r-08')
  })

  it('shows a held bill under needs a look, marked on hold', async () => {
    const held: InvoiceRow[] = [{ id: 2, number: 'UTL-4411', vendor_name: 'Electric Utility', status: 'on_hold', total: '1140.00', run_id: 'r-09', flags: [] }]
    const client = fakeClient(held)
    ;(client.run as ReturnType<typeof vi.fn>).mockImplementation(async (id: string) => (id === 'r-09' ? run09 : run13))
    await loaded(client)
    const needs = screen.getByRole('region', { name: /Needs a look/ })
    expect(within(needs).getByText('Electric Utility')).toBeInTheDocument()
    expect(within(needs).getByText('On hold')).toBeInTheDocument()
  })

  it('puts a bill whose booking failed under needs a look, saying so, and not under done', async () => {
    const failed: InvoiceRow[] = [{ id: 3, number: 'UTL-4411', vendor_name: 'Electric Utility', status: 'post_failed', total: '1140.00', run_id: 'r-09', flags: [] }]
    const client = fakeClient(failed)
    ;(client.run as ReturnType<typeof vi.fn>).mockImplementation(async () => ({ ...run09, status: 'post_failed', paused: false, pause: null }))
    await loaded(client)
    const needs = screen.getByRole('region', { name: /Needs a look/ })
    expect(within(needs).getByText('Approved, but booking failed: nothing was posted')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: /Done/ })).queryByText('Electric Utility')).not.toBeInTheDocument()
  })

  it('says nobody can approve a bill that has no entry yet, instead of naming a role', async () => {
    const newVendor: Run = { ...run08, pause: { ...run08.pause!, approver: 'clerk', controller_only: false, proposal: { lines: [] },
      flags: [{ code: 'VENDOR_NOT_FOUND', detail: '', amount: null, quantity: null }] } }
    const client = fakeClient()
    ;(client.startRun as ReturnType<typeof vi.fn>).mockImplementation(async (id: string) => (id === '08' ? newVendor : run09))
    await loaded(client)
    const needs = screen.getByRole('region', { name: /Needs a look/ })
    expect(within(needs).getByText('Not yet: no entry to book')).toBeInTheDocument()
    expect(within(needs).queryByText('Clerk')).not.toBeInTheDocument()
  })

  it("shows each problem bill's suggested step in a few words", async () => {
    const step = { code: 'BANK_CHANGED', decision: 'hold' as const, action: 'Hold until the new bank account is confirmed', why: '', then: '', reason: '', also: [] }
    const client = fakeClient()
    ;(client.startRun as ReturnType<typeof vi.fn>).mockImplementation(async (id: string) => (id === '08' ? { ...run08, next_step: step } : run09))
    await loaded(client)
    const needs = screen.getByRole('region', { name: /Needs a look/ })
    expect(within(needs).getByText('Next: Hold until the new bank account is confirmed')).toBeInTheDocument()
  })
})
