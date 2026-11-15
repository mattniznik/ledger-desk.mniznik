import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { BeforeAfter } from './BeforeAfter'

// The problem and what the desk does about it, in plain words, above every layout's demo.
describe('before and after', () => {
  it('sets today by hand against the desk, names the sources of its two figures, and lists the four steps', () => {
    render(<BeforeAfter />)
    const s = screen.getByRole('region', { name: 'The problem and what this does' })
    expect(within(s).getByText('Today, by hand')).toBeInTheDocument()
    expect(within(s).getByText('With ledger-desk')).toBeInTheDocument()
    expect(within(s).getByText(/types every bill in/)).toBeInTheDocument()
    expect(within(s).getByText(/AI reads the PDF or the phone photo/)).toBeInTheDocument()
    for (const name of [/Ardent Partners/, /AFP 2025/]) expect(within(s).getByRole('link', { name })).toHaveAttribute('href', expect.stringMatching(/^https:\/\//))
    const steps = within(s).getByRole('list', { name: 'How it works' })
    expect(within(steps).getAllByRole('listitem')).toHaveLength(4)
    expect(steps).toHaveTextContent('You decide')
  })
})
