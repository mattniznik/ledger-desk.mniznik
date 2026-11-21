// The system map: every piece of the bill workflow as one SVG graph, lit step by step while a run plays. It follows
// whatever is playing (the bill the desk has open, through the API, or a recorded run from the list under it: see
// map-feed.ts), plays the overcharge's recorded run once when it first scrolls into view, and has a guided tour of
// that run. Hover, focus or tap a node for one sentence on what it is.
//
// Which node and edge each step lights, and the captions, are in system-map.ts (pure, tested); this file only draws
// them and moves a packet along the lit edge. Two drawings of the same graph: wide (left to right) from 860 px,
// tall (two columns, top to bottom) below, so a phone never scrolls sideways. Under reduced motion nothing travels
// or plays on its own: each step is lit, and every step is listed.

import { useEffect, useEffectEvent, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react'

import './map.css'
import { useMotion } from '../live.ts'
import { publish, subscribeFeed, useFeed, useTourRequests, type Feed } from '../map-feed.ts'
import { flagWords, runOf, SITE } from '../site.ts'
import { eventsFromRecorded, mapBeats, mapGraph, mapState, TOOLS, TOUR_SAMPLE, tourFor, type Beat, type MapNode, type TourStep } from '../system-map.ts'

/* ---------------------------------------------------------------- the two drawings */

type Box = { x: number; y: number; w: number; h: number }
type Side = 'l' | 'r' | 't' | 'b'
type Geo = { tall: boolean; W: number; H: number; box: Record<string, Box>; route: Record<string, string> }

const GRAPH = mapGraph()

function anchor(b: Box, s: Side, off = 0): [number, number] {
  if (s === 'l') return [b.x - b.w / 2, b.y + off]
  if (s === 'r') return [b.x + b.w / 2, b.y + off]
  if (s === 't') return [b.x + off, b.y - b.h / 2]
  return [b.x + off, b.y + b.h / 2]
}
const NORMAL: Record<Side, [number, number]> = { l: [-1, 0], r: [1, 0], t: [0, -1], b: [0, 1] }
const r1 = (v: number) => Math.round(v * 10) / 10
function curve(a: Box, sa: Side, b: Box, sb: Side, offA = 0, offB = 0): string {
  const [x1, y1] = anchor(a, sa, offA)
  const [x2, y2] = anchor(b, sb, offB)
  const d = Math.min(120, Math.max(18, Math.hypot(x2 - x1, y2 - y1) * 0.42))
  const [ax, ay] = NORMAL[sa]
  const [bx, by] = NORMAL[sb]
  return `M${r1(x1)} ${r1(y1)} C${r1(x1 + ax * d)} ${r1(y1 + ay * d)} ${r1(x2 + bx * d)} ${r1(y2 + by * d)} ${r1(x2)} ${r1(y2)}`
}

function wideGeo(): Geo {
  const box: Record<string, Box> = {
    agent: { x: 545, y: 160, w: 170, h: 64 },
    bill: { x: 70, y: 300, w: 116, h: 54 },
    read: { x: 215, y: 300, w: 140, h: 64 },
    sources: { x: 368, y: 300, w: 126, h: 54 },
    checks: { x: 545, y: 300, w: 150, h: 64 },
    playbook: { x: 725, y: 300, w: 140, h: 64 },
    person: { x: 905, y: 300, w: 150, h: 64 },
    held: { x: 1112, y: 245, w: 124, h: 44 },
    rejected: { x: 1112, y: 330, w: 124, h: 44 },
    account: { x: 545, y: 440, w: 160, h: 54 },
    audit: { x: 725, y: 440, w: 150, h: 54 },
    sign: { x: 905, y: 440, w: 140, h: 54 },
    erp: { x: 1100, y: 440, w: 150, h: 54 },
    qbo: { x: 905, y: 555, w: 180, h: 50 },
    booked: { x: 1100, y: 555, w: 130, h: 46 },
  }
  TOOLS.forEach((t, i) => {
    box[`tool:${t}`] = { x: 380 + i * 165, y: 52, w: 150, h: 46 }
  })
  const B = (id: string) => box[id]
  const c = B('checks')
  const p = B('person')
  const route: Record<string, string> = {
    'bill>read': curve(B('bill'), 'r', B('read'), 'l'),
    'read>sources': curve(B('read'), 'r', B('sources'), 'l'),
    'sources>checks': curve(B('sources'), 'r', B('checks'), 'l'),
    'checks>agent': curve(c, 't', B('agent'), 'b'),
    'checks>account': curve(c, 'b', B('account'), 't'),
    'agent>playbook': curve(B('agent'), 'r', B('playbook'), 't'),
    'checks>playbook': curve(c, 'r', B('playbook'), 'l'),
    // a clean bill goes to the person under the next-step box
    'checks>person': `M${c.x + 50} ${c.y + c.h / 2} L${c.x + 50} 364 Q${c.x + 50} 372 ${c.x + 58} 372 L${p.x - 58} 372 Q${p.x - 50} 372 ${p.x - 50} 364 L${p.x - 50} ${p.y + p.h / 2}`,
    'playbook>person': curve(B('playbook'), 'r', p, 'l'),
    'person>audit': curve(p, 'b', B('audit'), 'r', -40),
    'person>sign': curve(p, 'b', B('sign'), 't', 20),
    'sign>erp': curve(B('sign'), 'r', B('erp'), 'l'),
    'erp>qbo': curve(B('erp'), 'b', B('qbo'), 'r', -40),
    'erp>booked': curve(B('erp'), 'b', B('booked'), 't'),
    'person>held': curve(p, 'r', B('held'), 'l', -14),
    'person>rejected': curve(p, 'r', B('rejected'), 'l', 14),
  }
  for (const t of TOOLS) route[`agent>tool:${t}`] = curve(B('agent'), 't', B(`tool:${t}`), 'b')
  return { tall: false, W: 1214, H: 600, box, route }
}

function tallGeo(): Geo {
  const L = 92
  const LW = 156
  const R = 256
  const RW = 144
  const at = (x: number, w: number, y: number, h = 44): Box => ({ x, y, w, h })
  const box: Record<string, Box> = {
    bill: at(L, LW, 30),
    read: at(R, RW, 30),
    checks: at(L, LW, 102),
    sources: at(R, RW, 102),
    account: at(L, LW, 176),
    agent: at(R, RW, 176),
    playbook: at(R, RW, 520),
    person: at(L, LW, 592),
    audit: at(R, RW, 592),
    held: at(L, LW, 662),
    sign: at(R, RW, 662),
    rejected: at(L, LW, 734),
    erp: at(R, RW, 734),
    booked: at(L, LW, 806),
    qbo: at(R, RW, 806),
  }
  TOOLS.forEach((t, i) => {
    box[`tool:${t}`] = at(L, LW, 246 + i * 48, 40)
  })
  const B = (id: string) => box[id]
  const c = B('checks')
  const p = B('person')
  const left = (from: Box, to: Box, off = 0) =>
    `M${from.x - from.w / 2} ${from.y + off} Q8 ${from.y + off} 8 ${from.y + off + 6} L8 ${to.y - 6} Q8 ${to.y} ${to.x - to.w / 2} ${to.y}`
  const route: Record<string, string> = {
    'bill>read': curve(B('bill'), 'r', B('read'), 'l'),
    'read>sources': curve(B('read'), 'b', B('sources'), 't'),
    'sources>checks': curve(B('sources'), 'l', c, 'r'),
    'checks>account': curve(c, 'b', B('account'), 't'),
    'checks>agent': curve(c, 'r', B('agent'), 'l', 8),
    'agent>playbook': curve(B('agent'), 'b', B('playbook'), 't'),
    // down the gap between the two columns
    'checks>playbook': `M${c.x + c.w / 2} ${c.y + 6} L172 ${c.y + 6} Q177 ${c.y + 6} 177 ${c.y + 11} L177 ${B('playbook').y - 5} Q177 ${B('playbook').y} 184 ${B('playbook').y}`,
    // down the left edge, past the tools
    'checks>person': left(c, p),
    'playbook>person': curve(B('playbook'), 'l', p, 't'),
    'person>audit': curve(p, 'r', B('audit'), 'l'),
    'person>held': curve(p, 'b', B('held'), 't'),
    'person>sign': curve(p, 'r', B('sign'), 'l', 14),
    'person>rejected': left(p, B('rejected'), 10),
    'sign>erp': curve(B('sign'), 'b', B('erp'), 't'),
    'erp>qbo': curve(B('erp'), 'b', B('qbo'), 't'),
    'erp>booked': curve(B('erp'), 'b', B('booked'), 'r', -40),
  }
  for (const t of TOOLS) route[`agent>tool:${t}`] = curve(B('agent'), 'l', B(`tool:${t}`), 'r')
  return { tall: true, W: 340, H: 840, box, route }
}

const WIDE = wideGeo()
const TALL = tallGeo()

/* ---------------------------------------------------------------- one node */

// Text that does not fit its box is cut with an ellipsis after it is drawn, by measuring it (the typeface is the
// visitor's pick, so a character count cannot know). Only the text node's value changes, so React keeps its own node.
function fitTexts(root: SVGSVGElement | null) {
  for (const el of root?.querySelectorAll<SVGTextElement>('text[data-max]') ?? []) {
    const node = el.firstChild
    const full = el.dataset.full ?? ''
    if (!node || node.nodeType !== 3) continue
    node.nodeValue = full
    const max = Number(el.dataset.max)
    if (el.getComputedTextLength() <= max) continue
    let n = full.length
    while (n > 1 && (node.nodeValue = full.slice(0, n - 1).trimEnd() + '…') && el.getComputedTextLength() > max) n--
  }
}

type NodeProps = { n: MapNode; b: Box; tall: boolean; cls: string; note?: string; status?: 'ok' | 'bad'; onHover: (id: string | null) => void; onPick: (id: string) => void }

function NodeView({ n, b, tall, cls, note, status, onHover, onPick }: NodeProps) {
  const ls = tall ? 12 : 14
  const ss = tall ? 10 : 11
  const lines = [note ?? n.sub]
  const pad = tall ? 10 : 12
  const outcome = n.kind === 'outcome'
  const room = b.w - (outcome ? 18 : pad + 8)
  const top = (b.h - (ls + 4 + lines.length * (ss + 3.5))) / 2
  const { w, h } = b
  return (
    <g
      className={`sm-n k-${n.kind} ${cls}`}
      transform={`translate(${b.x - w / 2} ${b.y - h / 2})`}
      tabIndex={0}
      role="button"
      aria-label={`${n.label}. ${n.info}`}
      onMouseEnter={() => onHover(n.id)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(n.id)}
      onBlur={() => onHover(null)}
      onClick={() => onPick(n.id)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onPick(n.id)
        }
      }}
    >
      <rect className="sm-halo" x={-5} y={-5} width={w + 10} height={h + 10} rx={outcome ? (h + 10) / 2 : 14} />
      <rect className="sm-shape" width={w} height={h} rx={outcome ? h / 2 : 10} />
      {!outcome && <rect className="sm-stripe" x={0} y={10} width={3} height={h - 20} rx={1.5} />}
      <text className="sm-l" x={outcome ? w / 2 : pad} y={top + ls} fontSize={ls} textAnchor={outcome ? 'middle' : 'start'} data-full={n.label} data-max={room - (status ? 10 : 0)}>
        {n.label}
      </text>
      {lines.map((l, i) => (
        <text key={i} className={note ? 'sm-s sm-note' : 'sm-s'} x={outcome ? w / 2 : pad} y={top + ls + 4 + (i + 1) * (ss + 3.5)} fontSize={ss} textAnchor={outcome ? 'middle' : 'start'} data-full={l} data-max={room}>
          {l}
        </text>
      ))}
      {status && (
        <g className={`sm-badge ${status}`} transform={`translate(${w - 3} 3)`}>
          <circle r={9} />
          <path d={status === 'ok' ? 'M-4 0 L-1 3 L4 -3' : 'M-3 -3 L3 3 M3 -3 L-3 3'} />
        </g>
      )}
    </g>
  )
}

/* ---------------------------------------------------------------- the map */

// The recorded runs a visitor can play on the map: an overcharge, a copy already paid, a bank change, a clean bill
// with no purchase order, and a bill with text aimed at an AI.
const RUNS = ['03', '07', '08', '09', '12'].map((id) => runOf(id))
const runTitle = (r: (typeof RUNS)[number]) => `${r.number}: ${r.flags.length ? flagWords(r.flags[0].code) : 'every check passed'}`
const recordedFeed = (r: (typeof RUNS)[number]) => ({ id: `map-${r.sample}-${Date.now()}`, title: runTitle(r), mode: 'replay' as const, events: eventsFromRecorded(r) })

type Mode = 'idle' | 'follow' | 'tour'

export function SystemMap({ focus = null, onPick, compact = false, className = '' }: { focus?: string | null; onPick?: (id: string) => void; compact?: boolean; className?: string }) {
  const motion = useMotion()
  const feed = useFeed()
  const tourAsks = useTourRequests()
  const root = useRef<HTMLDivElement>(null)
  const svg = useRef<SVGSVGElement>(null)
  const packet = useRef<SVGCircleElement>(null)
  const tourRun = runOf(TOUR_SAMPLE)
  const [tall, setTall] = useState(false)
  const [mode, setMode] = useState<Mode>('idle')
  const [beats, setBeats] = useState<(Beat | TourStep)[]>(() => mapBeats(eventsFromRecorded(tourRun)))
  // under reduced motion the default run shows whole from the start, every step lit
  const [k, setK] = useState(() => (motion ? -1 : beats.length - 1))
  const [playing, setPlaying] = useState(false)
  const [label, setLabel] = useState(`Recorded run: ${runTitle(tourRun)}`)
  const [hover, setHover] = useState<string | null>(null)
  const [pin, setPin] = useState<string | null>(null)
  const feedId = useRef<string | null>(null)
  const seen = useRef(false)

  const geo = tall ? TALL : WIDE
  const st = useMemo(() => mapState(beats, k), [beats, k])
  const active = st.active

  // wide from 860 px of room, tall below
  useLayoutEffect(() => {
    const el = root.current
    if (!el) return
    const measure = () => setTall(el.clientWidth < 860)
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const start = (next: (Beat | TourStep)[], m: Mode, text: string) => {
    setBeats(next)
    setMode(m)
    setLabel(text)
    // reduced motion: a run shows its last step at once; the tour waits for Next
    if (!motion) {
      setK(m === 'tour' ? 0 : next.length - 1)
      setPlaying(false)
      return
    }
    setK(-1)
    setPlaying(true)
  }

  // follow the run the page is playing; a new run starts over, more of the same run carries on. Through a
  // subscription, so the map's state changes in the store's callback, not inside an effect.
  const onFeed = useEffectEvent((feed: Feed) => {
    const next = mapBeats(feed.events)
    const what = feed.mode === 'desk' ? `The bill you opened: ${feed.title}` : `Recorded run: ${feed.title}`
    if (feed.id !== feedId.current || next.length < beats.length || mode !== 'follow') {
      if (feed.id === feedId.current && mode === 'tour') return // the tour keeps going until a new run starts
      feedId.current = feed.id
      start(next, 'follow', what)
      return
    }
    setBeats(next)
    if (!motion) setK(next.length - 1)
    else if (next.length - 1 > k) setPlaying(true)
  })
  useEffect(() => subscribeFeed((f) => onFeed(f)), [])

  const takeTour = () => {
    setPin(null)
    start(tourFor(tourRun), 'tour', `Tour: ${runTitle(tourRun)}`)
  }
  // a "Take the tour" button elsewhere on the page
  const asked = useRef(tourAsks)
  useEffect(() => {
    if (tourAsks === asked.current) return
    asked.current = tourAsks
    root.current?.scrollIntoView({ behavior: motion ? 'smooth' : 'auto', block: 'start' })
    takeTour()
  }, [tourAsks]) // eslint-disable-line react-hooks/exhaustive-deps

  // the edge flow and the halo pulse are endless CSS animations: paused while the map is off screen (state, so a
  // re-render keeps the class; it changes only when the map enters or leaves the screen)
  const [away, setAway] = useState(false)
  useEffect(() => {
    const el = root.current
    if (!el || !('IntersectionObserver' in window)) return
    const io = new IntersectionObserver((es) => es.forEach((e) => setAway(!e.isIntersecting)))
    io.observe(el)
    return () => io.disconnect()
  }, [])

  // plays once, the first time it scrolls into view
  useEffect(() => {
    const el = root.current
    if (!motion || !el || !('IntersectionObserver' in window)) return
    const io = new IntersectionObserver(
      (es) =>
        es.forEach((e) => {
          if (!e.isIntersecting || seen.current) return
          seen.current = true
          io.disconnect()
          if (!playing) {
            setK(-1)
            setPlaying(true)
          }
        }),
      { threshold: 0.3 },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [motion]) // eslint-disable-line react-hooks/exhaustive-deps

  // the clock: a step at a time, slower on the tour; it stops by itself at the last step
  const done = k >= beats.length - 1 && beats.length > 0
  const running = playing && !done
  useEffect(() => {
    if (!running) return
    const next = beats[k + 1]
    const ms = mode === 'tour' ? Math.min(6500, 2200 + (next.caption.length + ((next as TourStep).info?.length ?? 0)) * 14) : 1150
    const t = setTimeout(() => setK((x) => x + 1), k < 0 ? 250 : ms)
    return () => clearTimeout(t)
  }, [running, k, beats, mode])

  // cut what does not fit, once the type has loaded, and again whenever the drawing or a result changes
  const notesKey = JSON.stringify(st.notes) + Object.keys(st.status).join()
  useLayoutEffect(() => fitTexts(svg.current), [tall, notesKey])
  useEffect(() => {
    let live = true
    const again = () => live && fitTexts(svg.current)
    document.fonts?.ready.then(again)
    document.fonts?.addEventListener('loadingdone', again)
    return () => {
      live = false
      document.fonts?.removeEventListener('loadingdone', again)
    }
  }, [tall])

  // the packet travels the lit edge
  useEffect(() => {
    const p = packet.current
    if (!p) return
    p.style.opacity = '0'
    if (!motion || !active?.edge) return
    const path = svg.current?.querySelector<SVGPathElement>(`path[data-edge="${CSS.escape(active.edge)}"]`)
    if (!path) return
    const len = path.getTotalLength()
    const dur = mode === 'tour' ? 900 : 560
    let raf = 0
    const t0 = performance.now()
    const step = (now: number) => {
      const x = Math.min(1, (now - t0) / dur)
      const e = x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2
      const pt = path.getPointAtLength(len * (active.back ? 1 - e : e))
      p.setAttribute('cx', String(pt.x))
      p.setAttribute('cy', String(pt.y))
      p.style.opacity = x < 1 ? '1' : '0'
      if (x < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [active, motion, mode, tall])

  const pick = (id: string) => {
    setPin((p) => (p === id ? null : id))
    onPick?.(id)
  }
  const shownInfo = hover ?? pin ?? focus
  const infoNode = shownInfo ? GRAPH.nodes.find((x) => x.id === shownInfo) : null
  const tourStep = mode === 'tour' && active ? (active as TourStep) : null

  const nodeCls = (id: string) =>
    [st.nodes.includes(id) ? 'is-seen' : '', active?.node === id ? `is-on t-${active.tone}` : '', id === focus || id === pin ? 'is-focus' : '', id === hover ? 'is-hover' : '']
      .filter(Boolean)
      .join(' ')
  const rank = (id: string) => (id === active?.edge ? 2 : st.edges.includes(id) ? 1 : 0)
  const edgeOrder = [...GRAPH.edges].sort((a, b) => rank(a.id) - rank(b.id))

  return (
    <div ref={root} className={`sm${tall ? ' is-tall' : ' is-wide'}${compact ? ' is-compact' : ''}${mode === 'tour' ? ' is-tour' : ''}${away ? ' sm-away' : ''} ${className}`}>
      <div className="sm-top">
        <div className="sm-now">
          <span className={`sm-live${running ? ' on' : ''}`} aria-hidden="true" />
          <span>{label}</span>
        </div>
        <div className="sm-ctl">
          {mode === 'tour' ? (
            <>
              <button type="button" onClick={() => (setPlaying(false), setK((x) => Math.max(0, x - 1)))} disabled={k <= 0}>
                Back
              </button>
              <button type="button" onClick={() => (setPlaying(false), setK((x) => Math.min(beats.length - 1, x + 1)))} disabled={done}>
                Next
              </button>
              {motion && (
                <button type="button" onClick={() => (done ? (setK(0), setPlaying(true)) : setPlaying(!running))}>
                  {running ? 'Pause' : done ? 'Again' : 'Play'}
                </button>
              )}
            </>
          ) : (
            <>
              <button type="button" className="sm-go" data-tour="map" onClick={takeTour}>
                Take the tour
              </button>
              {motion && (
                <button type="button" onClick={() => (running ? setPlaying(false) : (done && setK(-1), setPlaying(true)))}>
                  {running ? 'Pause' : done ? 'Replay' : 'Play'}
                </button>
              )}
            </>
          )}
        </div>
      </div>

      <div className="sm-stage">
        <svg ref={svg} className="sm-svg" viewBox={`0 0 ${geo.W} ${geo.H}`} role="group" aria-label={`System map: ${GRAPH.nodes.length} pieces. Each node is a button that says what it is.`}>
          <defs>
            <pattern id="sm-dots" width="16" height="16" patternUnits="userSpaceOnUse">
              <circle cx="1.5" cy="1.5" r="1.1" className="sm-dot" />
            </pattern>
          </defs>
          <rect className="sm-grid" width={geo.W} height={geo.H} fill="url(#sm-dots)" />
          {!tall && (
            <g className="sm-zones" aria-hidden="true">
              <text x={305} y={16}>READ-ONLY LOOKUPS</text>
              <text x={12} y={252}>READ AND CHECKED</text>
              <text x={830} y={252}>A PERSON DECIDES</text>
              <text x={830} y={402}>THE BOOKS</text>
            </g>
          )}
          <g className="sm-edges">
            {edgeOrder.map((e) => (
              <path
                key={e.id}
                data-edge={e.id}
                d={geo.route[e.id]}
                className={`sm-e${st.edges.includes(e.id) ? ' is-seen' : ''}${active?.edge === e.id ? ` is-on t-${active.tone}${active.back ? ' back' : ''}` : ''}${e.id === 'erp>qbo' ? ' dash' : ''}`}
              />
            ))}
          </g>
          <g className="sm-nodes">
            {GRAPH.nodes.map((n) => (
              <NodeView key={n.id} n={n} b={geo.box[n.id]} tall={tall} cls={nodeCls(n.id)} note={st.notes[n.id]} status={st.status[n.id]} onHover={setHover} onPick={pick} />
            ))}
          </g>
          <circle ref={packet} className={`sm-pk t-${active?.tone ?? 'flow'}`} r={tall ? 5 : 6.5} cx={-20} cy={-20} />
        </svg>
      </div>

      {/* announced only during the tour, a step at a time as a person moves through it: a run playing by itself
          (on scroll, or for the bill the desk opened, perhaps off screen) would read out a caption a second */}
      <div className="sm-bar" aria-live={tourStep ? 'polite' : 'off'}>
        {tourStep ? (
          <>
            <p className="sm-step">
              Step {k + 1} of {beats.length} · <b>{tourStep.title}</b>
            </p>
            <p className="sm-info">{tourStep.info}</p>
            <p className={`sm-cap t-${tourStep.tone}`}>{tourStep.caption}</p>
          </>
        ) : (
          <p className={`sm-cap t-${active?.tone ?? 'flow'}`}>
            {active ? (
              <>
                <span className="sm-k">
                  {k + 1}/{beats.length}
                </span>{' '}
                {active.caption}
              </>
            ) : (
              'Each reading, check, lookup and decision lights the piece that did it. Take the tour, or replay a run.'
            )}
          </p>
        )}
      </div>

      <div className="sm-foot">
        <p className="sm-hint">
          {infoNode ? (
            <>
              <b>{infoNode.label}.</b> {infoNode.info}
            </>
          ) : (
            'Hover over or tap any piece to see what it is and why it is there.'
          )}
        </p>
        {!compact && (
          <div className="sm-runs" role="group" aria-label="Play a recorded run on the map">
            {RUNS.map((r) => (
              <button type="button" key={r.sample} data-ex={r.sample} aria-pressed={mode === 'follow' && feed?.title === runTitle(r) && !!feed?.id.startsWith('map-')} onClick={() => publish(recordedFeed(r))}>
                {runTitle(r)}
              </button>
            ))}
          </div>
        )}
        <details className="sm-list" open={!motion || undefined}>
          <summary>Every step of this run ({beats.length})</summary>
          <ol>
            {beats.map((b, i) => (
              <li key={i} className={`${i === k ? 'on' : ''} t-${b.tone}`}>
                <button type="button" onClick={() => (setPlaying(false), setK(i))}>
                  {b.caption}
                </button>
              </li>
            ))}
          </ol>
        </details>
      </div>
    </div>
  )
}

/** The map as a page section, with its heading, for the layouts that place it on its own. */
export function SystemMapSection({ className = '', head = true, style }: { className?: string; head?: boolean; style?: CSSProperties }) {
  return (
    <section className={`sm-sec ${className}`} id="map" style={style}>
      {head && (
        <div className="sm-head">
          <p className="sm-eyebrow">The system map</p>
          <h2 className="sm-h">Every piece, and what it did on a real bill.</h2>
          <p className="sm-lede">
            The bill, {SITE.model.name}, the source check, the {SITE.checks} checks, the agent with its {TOOLS.length - 1} read-only lookups and its draft
            email, the next step, the person, the signature, the books, the QuickBooks copy and the audit trail. It lights up with whatever bill the desk has
            open.
          </p>
        </div>
      )}
      <SystemMap />
    </section>
  )
}
