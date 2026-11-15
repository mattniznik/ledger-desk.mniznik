import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { fieldModel, howSteps, runOf, SITE } from '../site'
import { Field, Line, Pipeline, Player, Story } from './How'

// The animated How it works, with reduced motion on (jsdom has no canvas and no layout, so the drawing itself is
// left to the browser tests): what each view shows comes from the recorded runs and the eval, nothing plays on its
// own, and the dot field lists every step instead.

beforeAll(() => {
  window.matchMedia = vi.fn((q: string) => ({ matches: q.includes('reduce'), media: q, addEventListener: vi.fn(), removeEventListener: vi.fn() })) as unknown as typeof window.matchMedia
  window.ResizeObserver = class {
    observe() {}
    disconnect() {}
    unobserve() {}
  } as unknown as typeof ResizeObserver
  window.IntersectionObserver = class {
    observe() {}
    disconnect() {}
    unobserve() {}
  } as unknown as typeof IntersectionObserver
  HTMLCanvasElement.prototype.getContext = vi.fn(() => null) as unknown as HTMLCanvasElement['getContext']
})

const HOW = howSteps()

describe('the dot field', () => {
  it('under reduced motion lists every step with its count and offers no Play button', () => {
    render(<Field />)
    const f = fieldModel(SITE.field.cases)
    const list = screen.getByRole('list')
    expect(within(list).getAllByRole('listitem')).toHaveLength(6)
    expect(list).toHaveTextContent(f.captions[2])
    expect(list).toHaveTextContent(`${f.exact} of ${f.n} ended exactly as their answer key says`)
    expect(screen.queryByRole('button', { name: 'Play' })).not.toBeInTheDocument()
    expect(screen.getByRole('img')).toHaveAccessibleName(new RegExp(`${f.flagged} are flagged by the checks`))
  })
})

describe('the player', () => {
  // the player also keeps a hidden copy of every step to size its stage; the visible step is the live region
  const stage = (c: HTMLElement) => c.querySelector('.pstage[aria-live]') as HTMLElement

  it('waits for a click, then shows the step picked from the recorded run', () => {
    const { container } = render(<Player />)
    expect(stage(container)).toHaveTextContent('Real run · the bill') // the first step, still
    fireEvent.click(screen.getByRole('button', { name: /Claude looks into a problem/ }))
    const r = runOf('03')
    for (const l of r.lookups.filter((x) => x.tool !== 'draft_vendor_email')) expect(stage(container)).toHaveTextContent(l.result)
    expect(screen.getByRole('button', { name: /Claude looks into a problem/ })).toHaveAttribute('aria-current', 'step')
  })

  it('switches to another recorded run: the clean bill made no lookups', () => {
    const { container } = render(<Player />)
    fireEvent.click(screen.getByRole('button', { name: 'A clean bill' }))
    fireEvent.click(screen.getByRole('button', { name: /Claude looks into a problem/ }))
    expect(stage(container)).toHaveTextContent('No lookups: every check passed, so there was nothing to look into.')
  })
})

describe('the other views', () => {
  it('the scroll story steps through the bank-change run', () => {
    render(<Story />)
    expect(screen.getAllByText(HOW[0].title).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/REP-3307/).length).toBeGreaterThan(0)
  })

  it('the pipeline figure takes its numbers from the data', () => {
    render(<Pipeline />)
    expect(screen.getByRole('img')).toHaveAccessibleName(new RegExp(`${SITE.checks} checks in code`))
    expect(screen.getAllByText(new RegExp(`at most ${SITE.policies.max_lookups} lookups`)).length).toBeGreaterThan(0)
  })

  it('the moving line has a station per step and opens a step on a click, with nothing moving', () => {
    const { container } = render(<Line />)
    expect(container.querySelectorAll('.station')).toHaveLength(6)
    expect(screen.queryByRole('button', { name: /Play the flow/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: new RegExp(HOW[2].title) }))
    expect(screen.getByText(HOW[2].text)).toBeInTheDocument()
  })
})
