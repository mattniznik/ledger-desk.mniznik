import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Client } from './api'
import { HowItWorks } from './HowItWorks'

// The eval numbers on How it works come from site-data.json, which scripts/export_site.py writes from the
// results files; none is typed into the page. Different numbers here must show up on the page.
vi.mock('./site-data.json', () => ({
  default: {
    evals: [
      { model: 'scripted', tier: 'standard', cases: 50, end_result: 49, fields: 504, fields_correct: 504, pdf_fields: 424, photo_fields: 80, account_top1: 21, account_graded: 21, safe: 50, per_invoice_usd: 0, per_invoice_seconds: 0 },
      { model: 'subscription-claude-opus-5-5', tier: 'standard', cases: 7, end_result: 6, fields: 99, fields_correct: 98, pdf_fields: 90, photo_fields: 8, account_top1: 3, account_graded: 4, safe: 6, per_invoice_usd: 0.052, per_invoice_seconds: 12.3 },
      { model: 'subscription-claude-opus-5-5', tier: 'hard', cases: 2, end_result: 1, fields: 40, fields_correct: 39, pdf_fields: 20, photo_fields: 19, account_top1: 1, account_graded: 1, safe: 2, per_invoice_usd: 0.08, per_invoice_seconds: 16 },
    ],
    policies: { controller_from: 7500, price_tolerance_percent: 3 },
    recorded: { n: 9 },
    model: { id: 'claude-mock-1-0', name: 'Mock Model 1.0' },
  },
}))

describe('how it works, from the generated data', () => {
  it('shows the eval numbers the results files hold', () => {
    const client = { evals: vi.fn(async () => []) } as unknown as Client
    render(<HowItWorks client={client} />)
    const p = screen.getByText(/fields read correctly/)
    expect(p).toHaveTextContent('one eval run of 7 bills on Mock Model 1.0')
    expect(p).toHaveTextContent('98 of 99 fields read correctly (90 from PDFs, 8 from photos)')
    expect(p).toHaveTextContent('3 of 4 accounts suggested correctly')
    expect(p).toHaveTextContent('6 of 7 bills ended in the right state')
    expect(p).toHaveTextContent('1 of 7 reached the books without approval')
    expect(p).toHaveTextContent('On a harder set of 2')
    expect(p).toHaveTextContent('39 of 40 fields')
    expect(p).toHaveTextContent('About 12 seconds and 5 cents a bill')
  })

  it('quotes the approval limit the rules enforce', () => {
    const client = { evals: vi.fn(async () => []) } as unknown as Client
    render(<HowItWorks client={client} />)
    expect(screen.getByText(/\$7,500 or more/)).toBeInTheDocument()
  })
})
