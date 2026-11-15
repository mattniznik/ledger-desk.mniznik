import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { Desk as App } from './Desk'
import type { Client, Run, Sample } from './api'
import { TOUR } from './tour'

// The walkthrough: a morning in accounts payable, told step by step on the real screens. Each step
// says what the finance team struggles with, where the number comes from, and opens the bill or the
// screen that shows what the app does about it.

beforeAll(() => {
  URL.createObjectURL = vi.fn(() => 'blob:doc')
  URL.revokeObjectURL = vi.fn()
})

const samples: Sample[] = [
  ['03', 'PKG-20817', 'Packaging Supplier'], ['07', 'DAI-5521', 'Dairy Supplier'], ['08', 'REP-3307', 'Espresso Repair Service'],
  ['09', 'UTL-4411', 'Electric Utility'],
].map(([id, number, vendor_name]) => ({ id, number, vendor_name, total: '100.00', document: 'pdf', what_is_wrong: '', replay: true }))

function runOf(s: Sample): Run {
  return {
    run_id: `r-${s.id}`, sample: s.id, invoice_ref: `${s.id}-abc`, mode: 'replay', model: 'claude-opus-5-5', status: 'ready', paused: true,
    reason: '', metrics: null, entry_id: null, source_checks: {}, email_draft: null, seconds: null, due_date: null, mirror: null, flags: [],
    held: false, next_step: null, lookups: [],
    extraction: { vendor_name: s.vendor_name, number: s.number, date: '2026-11-01', total: s.total, po: null, remit_bank: '', remit_account_last4: '', lines: [] },
    pause: { invoice_ref: `${s.id}-abc`, status: 'ready', flags: [], approver: 'clerk', proposal: { lines: [] }, explanation: '', account_suggestion: null, controller_only: false, total: s.total },
  }
}

function fakeClient(): Client {
  const byId = Object.fromEntries(samples.map((s) => [`r-${s.id}`, runOf(s)]))
  return {
    samples: vi.fn(async () => samples),
    invoices: vi.fn(async () => []),
    startRun: vi.fn(async (id: string) => byId[`r-${id}`]),
    run: vi.fn(async (id: string) => byId[id]),
    document: vi.fn(async () => new Blob(['%PDF'], { type: 'application/pdf' })),
    audit: vi.fn(async () => []),
    verify: vi.fn(async () => ({ ok: true, checked: 0 })),
    evals: vi.fn(async () => []),
    reset: vi.fn(),
  } as unknown as Client
}

async function start() {
  const client = fakeClient()
  render(<App client={client} />)
  fireEvent.click(screen.getByRole('button', { name: /Walk through a morning in accounts payable/ }))
  return { client, tour: await screen.findByRole('complementary', { name: 'Walkthrough' }) }
}

describe('the walkthrough', () => {
  it('starts on the pile of bills, with the struggle, its source and what the app does', async () => {
    const { tour } = await start()
    expect(tour).toHaveTextContent('Step 1 of 6')
    expect(tour).toHaveTextContent('18.4%')
    expect(tour).toHaveTextContent('What the AI does: Claude reads every bill')
    expect(tour).toHaveTextContent('What code and people do:')
    expect(within(tour).getByRole('link', { name: /Ardent Partners/ })).toHaveAttribute('href', expect.stringMatching(/^https:\/\//))
    expect(within(tour).getByRole('button', { name: 'Back' })).toBeDisabled()
    expect(await screen.findByRole('heading', { name: 'Bills to pay' })).toBeInTheDocument()
  })

  it('opens the bill each step is about: the clean one, then the overcharge', async () => {
    const { client, tour } = await start()
    fireEvent.click(within(tour).getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(client.startRun).toHaveBeenCalledWith('09', 'replay'))
    expect(await screen.findByRole('button', { name: 'Back to the bills' })).toBeInTheDocument()
    fireEvent.click(within(tour).getByRole('button', { name: 'Next' }))
    expect(tour).toHaveTextContent('Step 3 of 6')
    await waitFor(() => expect(client.run).toHaveBeenLastCalledWith('r-03'))
  })

  it('ends on the audit trail, and Finish closes it', async () => {
    const { tour } = await start()
    for (let i = 1; i < TOUR.length; i++) fireEvent.click(within(tour).getByRole('button', { name: 'Next' }))
    expect(tour).toHaveTextContent('Step 6 of 6')
    expect(await screen.findByRole('heading', { name: 'Audit trail' })).toBeInTheDocument()
    fireEvent.click(within(tour).getByRole('button', { name: 'Finish' }))
    expect(screen.queryByRole('complementary', { name: 'Walkthrough' })).not.toBeInTheDocument()
  })

  it('cites a source for every number it quotes', () => {
    for (const step of TOUR) {
      if (/\d+(\.\d+)?%|\$\d/.test(step.struggle)) expect(step.source?.url).toMatch(/^https:\/\//)
    }
    expect(TOUR).toHaveLength(6)
  })

  it('says on every step what the AI does, apart from what code and people do', () => {
    for (const step of TOUR) {
      expect(step.ai).toMatch(/Claude/)
      expect(step.app.length).toBeGreaterThan(40)
    }
  })

  it('after two quick Nexts, only the newest step opens its bill', async () => {
    const { client, tour } = await start()
    const pending: Record<string, (r: Run) => void> = {}
    ;(client.startRun as ReturnType<typeof vi.fn>).mockImplementation((id: string) => new Promise<Run>((res) => { pending[id] = res }))
    fireEvent.click(within(tour).getByRole('button', { name: 'Next' })) // step 2: UTL-4411
    fireEvent.click(within(tour).getByRole('button', { name: 'Next' })) // step 3: PKG-20817
    await waitFor(() => expect(Object.keys(pending).sort()).toEqual(['03', '09']))
    pending['03'](runOf(samples[0]))
    await waitFor(() => expect(client.run).toHaveBeenCalledWith('r-03'))
    pending['09'](runOf(samples[3])) // the older step answers last
    await new Promise((r) => setTimeout(r, 20))
    expect(client.run).not.toHaveBeenCalledWith('r-09')
  })

  it('a bill the visitor opens while a step is loading is not replaced by the step', async () => {
    const client = fakeClient()
    render(<App client={client} />)
    const needsOrReady = await screen.findByRole('button', { name: 'Review PKG-20817' })
    await waitFor(() => expect(needsOrReady).toBeEnabled())
    let release: (() => void) | null = null
    ;(client.startRun as ReturnType<typeof vi.fn>).mockImplementation((id: string) => new Promise<Run>((res) => { release = () => res(runOf(samples.find((x) => x.id === id)!)) }))
    fireEvent.click(screen.getByRole('button', { name: /Walk through a morning in accounts payable/ }))
    const tour = await screen.findByRole('complementary', { name: 'Walkthrough' })
    fireEvent.click(within(tour).getByRole('button', { name: 'Next' })) // step 2 starts loading UTL-4411
    await waitFor(() => expect(release).not.toBeNull())
    fireEvent.click(screen.getByRole('button', { name: 'Review PKG-20817' }))
    await waitFor(() => expect(client.run).toHaveBeenCalledWith('r-03'))
    release!()
    await new Promise((r) => setTimeout(r, 20))
    expect(client.run).not.toHaveBeenCalledWith('r-09')
  })

  it('can start over with fresh bills, as a new visitor', async () => {
    const { client, tour } = await start()
    await waitFor(() => expect(client.samples).toHaveBeenCalled())
    const before = (client.samples as ReturnType<typeof vi.fn>).mock.calls.length
    fireEvent.click(within(tour).getByRole('button', { name: 'Start over with fresh bills' }))
    expect(client.reset).toHaveBeenCalled()
    await waitFor(() => expect((client.samples as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(before))
    expect(screen.getByRole('complementary', { name: 'Walkthrough' })).toHaveTextContent('Step 1 of 6')
  })
})

describe('the desk tabs', () => {
  it('say which tab is open', async () => {
    render(<App client={fakeClient()} />)
    const bills = screen.getByRole('button', { name: 'Bills' })
    expect(bills).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByRole('button', { name: 'Audit trail' }))
    expect(screen.getByRole('button', { name: 'Audit trail' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Bills' })).toHaveAttribute('aria-pressed', 'false')
  })
})
