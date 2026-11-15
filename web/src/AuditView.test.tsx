import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AuditView } from './AuditView'
import { MetricsFooter } from './MetricsFooter'
import type { AuditEntry, Client, Run } from './api'

const entries: AuditEntry[] = [
  { id: 1, session_id: 's', at: '2026-11-14T04:00:00+00:00', actor: 'system', action: 'session.created', entity: 's', detail: {}, prev_hash: 'genesis', hash: 'a'.repeat(64) },
  { id: 2, session_id: 's', at: '2026-11-14T04:00:01+00:00', actor: 'person', action: 'run.started', entity: '08-abc', detail: { invoice: '08' }, prev_hash: 'a'.repeat(64), hash: 'b'.repeat(64) },
  { id: 3, session_id: 's', at: '2026-11-14T04:00:02+00:00', actor: 'ai', action: 'workflow.read', entity: '08-abc', detail: { model: 'claude-opus-5-5' }, prev_hash: 'b'.repeat(64), hash: 'c'.repeat(64) },
]

function fakeClient(intact = true): Client {
  let broken = !intact
  return {
    audit: vi.fn(async () => entries),
    verify: vi.fn(async () => (broken ? { intact: false, rows: 3, first_bad_id: 3 } : { intact: true, rows: 3, first_bad_id: null })),
    tamper: vi.fn(async () => { broken = true; return { edited_id: 3 } }),
  } as unknown as Client
}

describe('the audit view', () => {
  it('lists every step with who did it, and verifies the chain', async () => {
    render(<AuditView client={fakeClient()} />)
    expect(await screen.findByText('workflow.read')).toBeInTheDocument()
    const rows = screen.getAllByRole('row').slice(1)
    expect(rows).toHaveLength(3)
    expect(within(rows[2]).getByText('ai')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Verify audit log' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Intact: all 3 rows check out')
  })

  it('shows what an edited row looks like: verify points at it', async () => {
    const client = fakeClient()
    render(<AuditView client={client} />)
    await screen.findByText('workflow.read')
    fireEvent.click(screen.getByRole('button', { name: /edit a row behind the app's back/i }))
    fireEvent.click(await screen.findByRole('button', { name: 'Verify audit log' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Broken at row 3')
    const bad = screen.getAllByRole('row').find((r) => r.classList.contains('bad'))
    expect(bad && within(bad).getByText('workflow.read')).toBeTruthy()
    expect(client.tamper).toHaveBeenCalledOnce()
  })
})

describe('the metrics footer', () => {
  it('shows calls, every kind of token, the API-equivalent cost, the time and where the run came from', () => {
    const run = {
      mode: 'replay', model: 'claude-opus-5-5', seconds: 22.7,
      metrics: { model_calls: 5, input_tokens: 8, cache_write_tokens: 9100, cache_read_tokens: 4200, output_tokens: 1530, cost_usd: 0.1187 },
    } as unknown as Run
    render(<MetricsFooter run={run} />)
    const footer = screen.getByRole('contentinfo')
    expect(footer).toHaveTextContent('5 model calls')
    expect(footer).toHaveTextContent('8 in + 9,100 cache write + 4,200 cache read, 1,530 out')
    expect(footer).toHaveTextContent('$0.1187 at API list prices')
    expect(footer).toHaveTextContent('22.7 s')
    expect(footer).toHaveTextContent('Replay of a real Claude run')
  })

  it('says plainly when a scripted run has no price and no model time', () => {
    const run = { mode: 'scripted', model: 'scripted', seconds: null, metrics: { model_calls: 2, input_tokens: 0, cache_write_tokens: 0, cache_read_tokens: 0, output_tokens: 0, cost_usd: null } } as unknown as Run
    render(<MetricsFooter run={run} />)
    expect(screen.getByRole('contentinfo')).toHaveTextContent('no model, no cost')
  })
})
