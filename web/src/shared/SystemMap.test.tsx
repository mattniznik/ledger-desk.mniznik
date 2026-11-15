import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { publish } from '../map-feed'
import { runOf } from '../site'
import { eventsFromRecorded, mapBeats, mapGraph, TOUR_SAMPLE } from '../system-map'
import { SystemMap } from './SystemMap'

// The map's drawing, with reduced motion on (jsdom has no layout, so the wide or tall choice and the packet are
// not tested here; the browser tests cover both sizes): one button per piece, every step listed and lit, the tour,
// and following the bill the desk opens.

beforeAll(() => {
  window.matchMedia = vi.fn((q: string) => ({ matches: q.includes('reduce'), media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() })) as unknown as typeof window.matchMedia
  window.ResizeObserver = class {
    observe() {}
    disconnect() {}
    unobserve() {}
  } as unknown as typeof ResizeObserver
  ;(SVGElement.prototype as unknown as { getComputedTextLength: () => number }).getComputedTextLength = () => 0
})

describe('the system map', () => {
  it('draws one button per piece, each saying what it is', () => {
    render(<SystemMap />)
    const nodes = mapGraph().nodes
    const svg = screen.getByRole('group', { name: /System map: \d+ pieces/ })
    expect(within(svg).getAllByRole('button')).toHaveLength(nodes.length)
    expect(within(svg).getByRole('button', { name: /^A person decides\./ })).toBeInTheDocument()
  })

  it('under reduced motion lists every step of the run and lights the last one', () => {
    render(<SystemMap />)
    const beats = mapBeats(eventsFromRecorded(runOf(TOUR_SAMPLE)))
    const list = screen.getByText(`Every step of this run (${beats.length})`).closest('details')!
    expect(list).toHaveAttribute('open')
    expect(within(list).getAllByRole('listitem')).toHaveLength(beats.length)
    expect(screen.getByText(beats.at(-1)!.caption, { selector: '.sm-cap *, .sm-cap' })).toBeInTheDocument()
  })

  it('takes the tour a step at a time', () => {
    render(<SystemMap />)
    fireEvent.click(screen.getByRole('button', { name: 'Take the tour' }))
    expect(screen.getByText(/^Step 1 of/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByText(/^Step 2 of/)).toBeInTheDocument()
  })

  it('follows the bill the desk opens', () => {
    render(<SystemMap />)
    act(() => publish({ id: 'desk-x', title: 'Dairy Supplier DAI-5521', mode: 'desk', events: eventsFromRecorded(runOf('07')) }))
    expect(screen.getByText('The bill you opened: Dairy Supplier DAI-5521')).toBeInTheDocument()
  })

  it('announces only the tour a person moves through, never a run playing by itself', () => {
    const { container } = render(<SystemMap />)
    const bar = container.querySelector('.sm-bar')!
    expect(bar).toHaveAttribute('aria-live', 'off')
    act(() => publish({ id: 'desk-y', title: 'Dairy Supplier DAI-5521', mode: 'desk', events: eventsFromRecorded(runOf('07')) }))
    expect(bar).toHaveAttribute('aria-live', 'off')
    fireEvent.click(screen.getByRole('button', { name: 'Take the tour' }))
    expect(container.querySelector('.sm-bar')).toHaveAttribute('aria-live', 'polite')
  })
})
