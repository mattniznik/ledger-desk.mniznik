// The page's Studio: twelve layouts, twenty-one colour sets, fifteen typefaces, and which one a visitor sees.
// Order: a ?layout= link (shown, not saved) > the visitor's saved pick > the site default. The five layouts built
// around the system map (10 to 14) are listed but marked as being built until the map exists: a link to one or a
// saved pick of one shows the default instead. Pure modules, checked without a browser.
import studioSource from './Studio.tsx?raw' // the panel's own source text
import { describe, expect, it } from 'vitest'
import { DEFAULT, FONTS, OPTIONS, PALETTES, PRESETS } from './presets'
import { cleanSearch, configFor, parseSaved, pickFor, resolveChoice, statusFor, STORAGE_KEY } from './choice'
import { contrast, fontsHref, solid, themeVars } from './theme'

const resolve = (query: string, saved: unknown = null) => resolveChoice({ query, saved: saved as never, presets: PRESETS, fallback: DEFAULT })

describe('the Studio presets', () => {
  it('twelve layouts: four section-built (01, 04-06), three one-column (07-09), five map-first (10-14)', () => {
    expect(OPTIONS.map((o) => o.id)).toEqual(['01', '04', '05', '06', '07', '08', '09', '10', '11', '12', '13', '14'])
    expect(OPTIONS.filter((o) => o.simple).map((o) => o.simple)).toEqual([1, 2, 3])
    expect(OPTIONS.filter((o) => o.cfg.look).map((o) => o.cfg.look)).toEqual(['canvas', 'waterfall', 'workshop', 'spec', 'garage'])
    for (const o of OPTIONS) {
      expect(PALETTES[o.cfg.palette], `${o.id} names a real palette`).toBeTruthy()
      expect(FONTS[o.cfg.font], `${o.id} names a real font`).toBeTruthy()
      if (!o.simple && !o.cfg.look) for (const k of ['hero', 'features', 'how', 'proof'] as const) expect(o.cfg[k], `${o.id} has a ${k} variant`).toBeTruthy()
    }
  })

  it('describes each layout in the bill desk\'s words, never a chat\'s', () => {
    for (const o of OPTIONS) expect(`${o.name} ${o.short}`).not.toMatch(/\b(chat|question|answer|recall|NHTSA)/i)
  })

  // the sibling demo's words (a parts store's support chat on recall data) must not show anywhere in the Studio:
  // not in a colour set's or a typeface's name, not in the panel's own text
  const SIBLING = /\b(chat|ask|answers?|recalls?|nhtsa|cars?|parts|store|live demo|garage)\b/i
  it('names every colour set and typeface in the bill desk\'s words', () => {
    for (const [k, p] of Object.entries(PALETTES)) expect(p.name, `palette ${k}`).not.toMatch(SIBLING)
    for (const [k, f] of Object.entries(FONTS)) expect(f.name, `font ${k}`).not.toMatch(SIBLING)
  })
  it('the Studio panel says nothing in the sibling demo\'s words', () => {
    expect(studioSource).not.toMatch(SIBLING)
  })

  // Changed on purpose when the map-first layouts landed: until then 10 to 14 were marked as being built and this
  // test pinned exactly those five; now every layout can be shown and nothing is held back.
  it('every layout can be shown: none is held back', () => {
    expect(OPTIONS.filter((o) => 'soon' in o).map((o) => o.id)).toEqual([])
  })

  it('twenty-one palettes, split dark and light, each with every colour key', () => {
    const keys = ['bg', 'card', 'card2', 'line', 'tx', 'mu', 'a1', 'a2', 'a3', 'acc', 'on', 'mark']
    expect(Object.keys(PALETTES)).toHaveLength(21)
    for (const [k, p] of Object.entries(PALETTES)) for (const c of keys) expect(typeof (p as Record<string, unknown>)[c], `${k}.${c}`).toBe('string')
    const light = Object.values(PALETTES).filter((p) => p.light).length
    expect(light > 0 && light < 21).toBe(true)
  })

  // text and muted text 4.5:1 on the background, the accent 3:1, button text 4.5:1 on each gradient stop (and on
  // the fill where a palette has its own button fill)
  it('every palette meets the contrast it claims', () => {
    for (const [k, p] of Object.entries(PALETTES)) {
      expect(contrast(p.tx, p.bg), `${k}: text on background`).toBeGreaterThanOrEqual(4.5)
      expect(contrast(p.mu, p.bg), `${k}: muted text on background`).toBeGreaterThanOrEqual(4.5)
      expect(contrast(p.acc, p.bg), `${k}: accent on background`).toBeGreaterThanOrEqual(3)
      for (const a of [p.a1, p.a2, p.a3]) expect(contrast(p.on, a), `${k}: button text on ${a}`).toBeGreaterThanOrEqual(4.5)
      if (p.fill) expect(contrast(p.onFill!, p.fill), `${k}: button text on its fill`).toBeGreaterThanOrEqual(4.5)
    }
  })

  // the status colours are text too ("found in the PDF", "differs from the bank details on file"): 4.5:1 on the
  // background and on a card, a translucent card blended over the background first
  it('every palette gives readable status colours', () => {
    const font = Object.values(FONTS)[0]
    for (const [k, p] of Object.entries(PALETTES)) {
      const v = themeVars(p, font)
      for (const name of ['--ok', '--bad', '--warn']) {
        for (const [where, under] of [['background', p.bg], ['card', solid(p.card, p.bg)]]) {
          expect(contrast(v[name], under), `${k}: ${name} on the ${where}`).toBeGreaterThanOrEqual(4.5)
        }
      }
    }
  })

  it('fifteen font pairings; the default is Editorial on Trace lilac with Instrument Serif and DM Sans', () => {
    expect(Object.keys(FONTS)).toHaveLength(15)
    // chosen by the owner on 2026-11-21: Editorial (06) on Trace lilac with Instrument Serif + DM Sans; until then
    // layout 01 on Golden hour on paper with Barlow Condensed caps, the sibling demos' default look
    expect(DEFAULT).toEqual({ option: '06', palette: 'lilac', font: 'serif' })
    expect(PALETTES.lilac.name).toBe('Trace lilac')
    expect(FONTS.serif.head).toMatch(/Instrument Serif/)
    expect(FONTS.serif.body).toMatch(/DM Sans/)
    expect(FONTS.condensed.head).toMatch(/Barlow Condensed/)
    expect(FONTS.condensed.body).toMatch(/DM Sans/)
    expect(FONTS.condensed.caps).toBe(true)
  })
})

describe('which look a visitor sees', () => {
  it('a ?layout= link is shown and says it came from a link', () => {
    expect(resolve('?layout=04')).toEqual({ option: '04', palette: 'mono', font: 'mono', source: 'link' })
    expect(resolve('?layout=05&palette=ocean&font=serif')).toEqual({ option: '05', palette: 'ocean', font: 'serif', source: 'link' })
    expect(resolve('?layout=06&palette=nope&font=nope')).toEqual({ option: '06', palette: 'coverPaper', font: 'serif', source: 'link' })
    expect(resolve('?layout=07', { option: '04', palette: 'lime', font: 'inter' }).option).toBe('07')
  })

  it('without a link the saved pick shows; without either, the default', () => {
    expect(resolve('', { option: '08', palette: 'lime', font: 'inter' })).toEqual({ option: '08', palette: 'lime', font: 'inter', source: 'saved' })
    expect(resolve('')).toEqual({ option: '06', palette: 'lilac', font: 'serif', source: 'default' })
    expect(resolve('?layout=99')).toEqual({ option: '06', palette: 'lilac', font: 'serif', source: 'default' })
    expect(resolve('', { option: '99' }).source).toBe('default')
  })

  // Changed on purpose when the map-first layouts landed: a link or a saved pick of 10 to 14 used to fall through to
  // the default; now each is shown like any other layout.
  it('a map-first layout is shown from a link or a saved pick', () => {
    expect(resolve('?layout=10')).toEqual({ option: '10', palette: 'canvasNight', font: 'geist', source: 'link' })
    expect(resolve('?layout=12', { option: '05' })).toEqual({ option: '12', palette: 'workshop', font: 'archivo', source: 'link' })
    expect(resolve('', { option: '14', palette: 'garage', font: 'outfit' })).toEqual({ option: '14', palette: 'garage', font: 'outfit', source: 'saved' })
  })

  it('storage can hold anything: only an object counts as a saved pick', () => {
    expect(STORAGE_KEY).toBe('ledger-desk-choice')
    expect(parseSaved('{"option":"04"}')).toEqual({ option: '04' })
    for (const raw of [null, '', 'not json', '[1,2]', '42', '"04"']) expect(parseSaved(raw)).toBeNull()
  })

  it('configFor merges the layout\'s own sections with the chosen colours and type', () => {
    const cfg = configFor({ option: '01', palette: 'ocean', font: 'plex' }, PRESETS)
    expect([cfg.hero, cfg.palette, cfg.font, cfg.simple]).toEqual(['search', 'ocean', 'plex', null])
    expect(configFor({ option: '09', palette: 'demo', font: 'serif' }, PRESETS).simple).toBe(3)
  })

  it('a Studio pick: a layout brings its own look, a palette or font changes only itself', () => {
    const cur = { option: '01', palette: 'coverPaper', font: 'condensed' }
    expect(pickFor(cur, { option: '04' }, PRESETS)).toEqual({ option: '04', palette: 'mono', font: 'mono' })
    expect(pickFor(cur, { palette: 'lime' }, PRESETS)).toEqual({ option: '01', palette: 'lime', font: 'condensed' })
    expect(pickFor(cur, { font: 'inter' }, PRESETS)).toEqual({ option: '01', palette: 'coverPaper', font: 'inter' })
    expect(pickFor(cur, { option: '01' }, PRESETS)).toEqual({ option: '01', palette: 'coverPaper', font: 'condensed' })
  })

  it('after a pick the link\'s layout, palette and font are dropped, other parameters stay', () => {
    expect(cleanSearch('?layout=04&palette=mono&font=mono')).toBe('')
    expect(cleanSearch('?layout=04&x=1')).toBe('?x=1')
    expect(cleanSearch('')).toBe('')
  })

  it('the status line says where the look came from', () => {
    expect(statusFor('saved')).toMatch(/^Saved in this browser/)
    expect(statusFor('link')).toMatch(/not saved/)
    expect(statusFor('default')).toMatch(/default look/)
  })
})

describe('the theme', () => {
  it('sets every colour variable, and picks readable text for the accent', () => {
    const v = themeVars(PALETTES.coverPaper, FONTS.condensed)
    for (const k of ['--bg', '--card', '--card2', '--line', '--tx', '--mu', '--a1', '--a2', '--a3', '--acc', '--on', '--mark', '--fh', '--fb', '--hw', '--ok', '--bad', '--fill', '--on-fill', '--on-acc']) expect(k in v, k).toBe(true)
    expect(v['--bg']).toBe('#f6f0e6')
    expect(v['--on-acc']).toBe('#ffffff')
    expect(themeVars(PALETTES.coverDark, FONTS.grotesk)['--on-acc']).toBe('#111111')
    expect(themeVars(PALETTES.paperRust, FONTS.serif)['--fill']).toBe('#1a1714')
  })

  it('loads fonts from Google Fonts: the chosen pairing plus the mono labels, each family once', () => {
    const href = fontsHref([FONTS.condensed])
    expect(href).toMatch(/^https:\/\/fonts\.googleapis\.com\/css2\?/)
    expect(href).toMatch(/family=Barlow\+Condensed/)
    expect(href).toMatch(/family=JetBrains\+Mono/)
    expect(href).toMatch(/&display=swap$/)
    expect(href.match(/family=DM\+Sans/g)).toHaveLength(1)
    expect(fontsHref([FONTS.system])).toBe('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap')
    const all = fontsHref(Object.values(FONTS))
    expect(all.match(/family=DM\+Sans/g)).toHaveLength(1)
    expect(all.match(/family=JetBrains\+Mono/g)).toHaveLength(1)
  })
})
