// Motion and the jump to the desk, shared by every layout.

import { useEffect, useState } from 'react'

const reduce = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

/** false when the visitor asked for reduced motion: animations then show their last frame. */
export function useMotion(): boolean {
  const [motion, setMotion] = useState(() => !reduce())
  useEffect(() => {
    if (typeof matchMedia !== 'function') return
    const q = matchMedia('(prefers-reduced-motion: reduce)')
    const on = () => setMotion(!q.matches)
    q.addEventListener('change', on)
    return () => q.removeEventListener('change', on)
  }, [])
  return motion
}

/** Bring the desk into view. */
export function jumpToDesk(motion: boolean) {
  document.getElementById('desk')?.scrollIntoView({ behavior: motion ? 'smooth' : 'auto', block: 'start' })
}
