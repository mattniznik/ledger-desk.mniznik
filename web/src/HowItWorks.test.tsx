import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Client } from './api'
import { HowItWorks } from './HowItWorks'

describe('how it works', () => {
  it('says who the app is for, what it does for them and what stays with people, then shows the evals', async () => {
    const client = { evals: vi.fn(async () => []) } as unknown as Client
    render(<HowItWorks client={client} />)
    expect(screen.getByRole('heading', { name: 'Who it is for' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'What it does for them' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'What stays with people' })).toBeInTheDocument()
    // copy of the rules in rules.py (CONTROLLER_FROM $5,000) and authority.py (bank change: controller and phone check);
    // not linked to those constants, so a change there needs this text changed by hand
    expect(screen.getByText(/\$5,000 or more/)).toBeInTheDocument()
    expect(screen.getByText(/phone call to the number already on file/)).toBeInTheDocument()
    expect(await screen.findByText(/No eval runs yet/)).toBeInTheDocument()
  })

  it('says what the problem costs, with the source of every number', async () => {
    const client = { evals: vi.fn(async () => []) } as unknown as Client
    render(<HowItWorks client={client} />)
    expect(screen.getByRole('heading', { name: 'The problem it solves' })).toBeInTheDocument()
    for (const n of ['18.4%', '21.9%', '45%', '22%', '21,442']) expect(screen.getByText(new RegExp(n.replace('.', '\\.')))).toBeInTheDocument()
    for (const name of [/Ardent Partners/, /AFP 2025/, /FBI/]) expect(screen.getByRole('link', { name })).toHaveAttribute('href', expect.stringMatching(/^https:\/\//))
    await screen.findByText(/No eval runs yet/)
  })

  it('shows where the AI helps and where code and people take over, with how well it measured', async () => {
    const client = { evals: vi.fn(async () => []) } as unknown as Client
    render(<HowItWorks client={client} />)
    const table = screen.getByRole('table', { name: 'Where the AI helps' })
    for (const col of ['The problem', 'What the AI does', 'What code does', 'What people do']) expect(within(table).getByRole('columnheader', { name: col })).toBeInTheDocument()
    expect(within(table).getAllByRole('row').length).toBeGreaterThanOrEqual(6)
    expect(screen.getByText(/504 of 504 fields/)).toBeInTheDocument()
    await screen.findByText(/No eval runs yet/)
  })
})
