import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Testing Library unmounts between tests on its own only when Vitest globals are on; they are
// off here, so without this a test can click a component left over from the one before it.
afterEach(() => cleanup())
