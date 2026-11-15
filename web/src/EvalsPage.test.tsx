import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { EvalsPage } from './EvalsPage'
import type { Client, EvalRun, EvalSummary } from './api'

const summary: EvalSummary = {
  cases: 50,
  end_result: { exact: 49, status_ok: 49, failed: ['v34'], known_limits: ['v34'] },
  flags: {
    BANK_CHANGED: { tp: 5, fp: 0, fn: 0, precision: 1, recall: 1 },
    SUSPICIOUS_TEXT: { tp: 7, fp: 0, fn: 1, precision: 1, recall: 0.875 },
  },
  reading: { pdf: { cases: 42, fields: 424, fields_correct: 424 }, photo: { cases: 8, fields: 80, fields_correct: 80 } },
  account: { graded: 21, top1: 21 },
  safety: { graded: 50, passed: 50 },
  cost: { usd: 3.5652, per_invoice_usd: 0.0713 },
  time: { seconds: 789.34, per_invoice_seconds: 15.79 },
  errors: [],
}

const runs: EvalRun[] = [
  { name: 'm5a-scripted', version: 'm5a', tier: 'standard', model: 'scripted', date: '2026-11-14', proves: 'the graders and the rules, not a model', summary: { ...summary, cost: { usd: null, per_invoice_usd: null } } },
  { name: 'm5a-subscription-claude-opus-5-5', version: 'm5a', tier: 'standard', model: 'subscription-claude-opus-5-5', date: '2026-11-14', proves: 'the model', summary },
]

function fakeClient(list: EvalRun[] = runs): Client {
  return {
    evals: vi.fn(async () => list),
    evalRun: vi.fn(async (name: string) => ({
      ...list.find((r) => r.name === name)!,
      cases: [
        { id: '12', document: 'pdf', exact: true, known_limit: false, reading_wrong: [], status: 'exception' },
        { id: 'v34', document: 'pdf', exact: false, known_limit: true, reading_wrong: [], status: 'ready' },
      ],
    })),
  } as unknown as Client
}

describe('the evals page', () => {
  it('lists each run with its headline numbers and says what a scripted run proves', async () => {
    render(<EvalsPage client={fakeClient()} />)
    const rows = (await screen.findAllByRole('row')).slice(1)
    expect(rows).toHaveLength(2)
    const real = rows[1]
    expect(within(real).getByText('subscription-claude-opus-5-5')).toBeInTheDocument()
    expect(within(real).getByText('49 / 50')).toBeInTheDocument()
    expect(within(real).getByText('504 / 504')).toBeInTheDocument() // pdf and photo fields together
    expect(within(real).getByText('$3.57')).toBeInTheDocument()
    expect(within(rows[0]).getByText(/proves the graders and the rules, not a model/)).toBeInTheDocument()
  })

  it('opens a run: precision and recall per flag, and the known limit named', async () => {
    const client = fakeClient()
    render(<EvalsPage client={client} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Open m5a-subscription-claude-opus-5-5' }))
    const flags = await screen.findByRole('table', { name: 'Flags' })
    expect(within(flags).getByText('SUSPICIOUS_TEXT')).toBeInTheDocument()
    expect(within(flags).getByText('0.88')).toBeInTheDocument()
    expect(screen.getByText(/v34/)).toHaveTextContent(/known limit/i)
    expect(client.evalRun).toHaveBeenCalledWith('m5a-subscription-claude-opus-5-5')
  })

  it('says so plainly when there are no results yet', async () => {
    render(<EvalsPage client={fakeClient([])} />)
    expect(await screen.findByText(/No eval runs yet/)).toBeInTheDocument()
  })
})
