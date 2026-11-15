// What the system map should play, handed over by whatever is playing a run: the map's own list of recorded runs,
// or the desk (the bill a visitor opens, and what they decide on it). One run at a time; a new id starts the map
// over, the same id with more steps carries it on. A module-level store, so the desk and the map need no shared
// parent.

import { useSyncExternalStore } from 'react'

import type { MapEvent } from './system-map.ts'

export type Feed = {
  id: string
  title: string
  // "replay": a recorded run from the site data; "desk": the bill a visitor has open, through the API
  mode: 'replay' | 'desk'
  events: MapEvent[]
}

let current: Feed | null = null
const listeners = new Set<() => void>()

export function publish(feed: Feed) {
  current = feed
  for (const l of listeners) l()
}

const subscribe = (l: () => void) => {
  listeners.add(l)
  return () => listeners.delete(l)
}

/** Calls the listener with each run published from now on; returns the way to stop. */
export function subscribeFeed(listener: (feed: Feed) => void): () => void {
  const l = () => current && listener(current)
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

/** The run the map should show, or null before anything has played. */
export function useFeed(): Feed | null {
  return useSyncExternalStore(subscribe, () => current, () => null)
}

// "Take the tour" buttons outside the map (a hero, a nav) ask the map to start it.
let tours = 0
const tourListeners = new Set<() => void>()

export function requestTour() {
  tours++
  for (const l of tourListeners) l()
}

/** A count that goes up each time a tour is asked for. */
export function useTourRequests(): number {
  return useSyncExternalStore(
    (l) => {
      tourListeners.add(l)
      return () => tourListeners.delete(l)
    },
    () => tours,
    () => 0,
  )
}
