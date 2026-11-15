// No flash of the wrong colours: index.html carries a small inline script (made by bootScript, injected by
// vite.config.ts) that paints the visitor's background before the page's JavaScript has loaded, and hides the page
// until it has rendered, with a 6 s failsafe. It must pick the same palette the page will: these tests run the
// script in a sandbox and compare it with resolveChoice for links, saved picks, the default, layouts still being
// built, and junk.
import { describe, expect, it } from 'vitest'
import { bootScript } from './boot'
import { resolveChoice, STORAGE_KEY } from './choice'
import { DEFAULT, PALETTES, PRESETS } from './presets'

function run(search: string, stored: string | null, storageThrows = false) {
  const style: Record<string, string> = {}
  const classes = new Set<string>()
  const timers: { fn: () => void; ms: number }[] = []
  const sandbox = {
    URLSearchParams,
    JSON,
    location: { search },
    localStorage: {
      getItem: (k: string) => {
        if (storageThrows) throw new Error('blocked')
        return k === STORAGE_KEY ? stored : null
      },
    },
    document: { documentElement: { style, classList: { add: (c: string) => classes.add(c), remove: (c: string) => classes.delete(c) } } },
    setTimeout: (fn: () => void, ms: number) => timers.push({ fn, ms }),
  }
  // the script's free names (location, localStorage, document, ...) become this function's parameters: a sandbox
  // with nothing else in reach
  const names = Object.keys(sandbox) as (keyof typeof sandbox)[]
  new Function(...names, bootScript(PRESETS, STORAGE_KEY))(...names.map((k) => sandbox[k]))
  return { style, classes, timers }
}

function expected(search: string, stored: string | null) {
  let saved = null
  try {
    saved = JSON.parse(stored ?? 'null')
  } catch {
    saved = null
  }
  const c = resolveChoice({ query: search, saved: saved && typeof saved === 'object' && !Array.isArray(saved) ? saved : null, presets: PRESETS, fallback: DEFAULT })
  return PALETTES[c.palette]
}

describe('the boot script', () => {
  it('paints the same background the page resolves', () => {
    const cases: [string, string | null][] = [
      ['', null],
      ['', '{"option":"04"}'],
      ['', '{"option":"08","palette":"lime","font":"inter"}'],
      ['', '{"option":"05","palette":"nope"}'],
      ['', 'not json'],
      ['', '[1,2]'],
      ['', '{"option":"99","palette":"lime"}'],
      ['', '{"option":"10","palette":"canvasNight"}'],
      ['?layout=04', null],
      ['?layout=06&palette=ocean', '{"option":"08","palette":"lime"}'],
      ['?layout=99', '{"option":"09"}'],
      ['?layout=07&palette=nope', null],
      ['?layout=11', '{"option":"06"}'],
    ]
    for (const [search, stored] of cases) {
      const p = expected(search, stored)
      const { style } = run(search, stored)
      expect(style.background, `${search} ${stored}`).toBe(p.bg)
      expect(style.colorScheme, `${search} ${stored}`).toBe(p.light ? 'light' : 'dark')
    }
  })

  it('hides the page until it renders, with a 6 s failsafe', () => {
    const { classes, timers } = run('', null)
    expect(classes.has('boot')).toBe(true)
    expect(timers.map((t) => t.ms)).toEqual([6000])
    timers[0].fn()
    expect(classes.has('boot')).toBe(false)
  })

  it('blocked storage still gets the default background', () => {
    expect(run('', null, true).style.background).toBe(PALETTES[DEFAULT.palette].bg)
  })
})
