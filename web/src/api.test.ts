import { describe, expect, it, vi } from 'vitest'
import { ApiError, createClient } from './api'

function memoryStorage(): Storage {
  const m = new Map<string, string>()
  return {
    getItem: (k) => m.get(k) ?? null,
    setItem: (k, v) => void m.set(k, v),
    removeItem: (k) => void m.delete(k),
    clear: () => m.clear(),
    key: (i) => [...m.keys()][i] ?? null,
    get length() { return m.size },
  }
}

function reply(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
}

describe('the API client', () => {
  it('creates the visitor session once and sends it with every call', async () => {
    const fetchMock = vi.fn((url: string) =>
      url.endsWith('/sessions') ? reply(201, { session_id: 's-1' }) : reply(200, { invoices: [] }),
    )
    const client = createClient(fetchMock as unknown as typeof fetch, memoryStorage())
    await client.invoices()
    await client.invoices()
    const calls = fetchMock.mock.calls as unknown as [string, RequestInit][]
    expect(calls.filter(([u]) => u.endsWith('/sessions'))).toHaveLength(1)
    const sent = calls.filter(([u]) => u.endsWith('/invoices')).map(([, init]) => (init.headers as Record<string, string>)['X-Session-Id'])
    expect(sent).toEqual(['s-1', 's-1'])
  })

  it('starts a new session once when the API no longer knows the stored one', async () => {
    const storage = memoryStorage()
    storage.setItem('ledger-desk-session', 'old')
    let invoiceCalls = 0
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/sessions')) return reply(201, { session_id: 'new' })
      invoiceCalls += 1
      return invoiceCalls === 1 ? reply(404, { detail: 'no such session; it may have expired' }) : reply(200, { invoices: [] })
    })
    const client = createClient(fetchMock as unknown as typeof fetch, storage)
    expect(await client.invoices()).toEqual([])
    expect(storage.getItem('ledger-desk-session')).toBe('new')
  })

  it("turns a refusal into an error carrying the API's status and reason", async () => {
    const fetchMock = vi.fn((url: string) =>
      url.endsWith('/sessions') ? reply(201, { session_id: 's' }) : reply(403, { detail: 'only the controller may approve $13,423.00' }),
    )
    const client = createClient(fetchMock as unknown as typeof fetch, memoryStorage())
    const err = await client.decide('r1', { role: 'clerk', decision: 'approve' }).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(403)
    expect(err.message).toBe('only the controller may approve $13,423.00')
  })
})

describe('where the API is', () => {
  it('calls the address set at build time when the page and the API are on two hostnames', async () => {
    vi.stubEnv('VITE_API_BASE', 'https://api.example.test')
    const calls: string[] = []
    const fetchImpl = vi.fn((url: string) => {
      calls.push(url)
      return reply(200, url.endsWith('/sessions') ? { session_id: 's-1' } : { samples: [] })
    }) as unknown as typeof fetch
    await createClient(fetchImpl, memoryStorage()).samples()
    expect(calls.every((u) => u.startsWith('https://api.example.test/'))).toBe(true)
    vi.unstubAllEnvs()
  })

  it('calls /api on its own host when no address is set (the dev server proxies it)', async () => {
    const calls: string[] = []
    const fetchImpl = vi.fn((url: string) => {
      calls.push(url)
      return reply(200, url.endsWith('/sessions') ? { session_id: 's-1' } : { samples: [] })
    }) as unknown as typeof fetch
    await createClient(fetchImpl, memoryStorage()).samples()
    expect(calls.every((u) => u.startsWith('/api/'))).toBe(true)
  })
})
