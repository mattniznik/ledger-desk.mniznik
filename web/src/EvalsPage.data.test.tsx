import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Client, EvalRun, EvalSummary } from './api'
import { EvalsPage } from './EvalsPage'

// The eval set's size on the Evals section comes from site-data.json, never typed in: other numbers here must show.
vi.mock('./site-data.json', () => ({
  default: {
    evals: [
      { model: 'subscription-claude-opus-5-5', tier: 'standard', cases: 20 },
      { model: 'subscription-claude-opus-5-5', tier: 'hard', cases: 4 },
    ],
    recorded: { n: 5 },
  },
}))

const summary: EvalSummary = {
  cases: 20,
  end_result: { exact: 20, status_ok: 20, failed: [], known_limits: [] },
  flags: {},
  reading: { pdf: { cases: 18, fields: 180, fields_correct: 180 }, photo: { cases: 2, fields: 20, fields_correct: 20 } },
  account: { graded: 5, top1: 5 },
  safety: { graded: 20, passed: 20 },
  cost: { usd: 1, per_invoice_usd: 0.05 },
  time: { seconds: 100, per_invoice_seconds: 5 },
  errors: [],
}
const run: EvalRun = { name: 'r1', version: 'v1', tier: 'standard', model: 'subscription-claude-opus-5-5', date: '2026-11-14', proves: 'the model', summary }

describe('the evals section, from the generated data', () => {
  it('says how many bills the eval holds, from the results files', async () => {
    const client = { evals: vi.fn(async () => [run]) } as unknown as Client
    render(<EvalsPage client={client} />)
    expect(await screen.findByText(/20 standard invoices \(5 samples and 15 variants\) and a hard tier of 4/)).toBeInTheDocument()
  })
})
