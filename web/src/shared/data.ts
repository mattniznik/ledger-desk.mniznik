// What every layout reads besides the desk: the generated site data (site.ts) and the few fixed words every
// layout repeats. No number here is typed in.

import { SITE } from '../site.ts'

export { SITE }

export const COMPANY = 'Coffee Roastery'

// The footer every layout ends with, matching NOTICE.
export const DISCLAIMER =
  'A fictional company with invented data, for a demo: every vendor, bank, tax id and amount is made up. Not affiliated with or endorsed by Intuit; QuickBooks is a trademark of Intuit Inc.'

// What the system is made of, for the footers.
export const STACK = ['Python', 'FastAPI', 'LangGraph', 'PostgreSQL', 'React', 'Vite', SITE.model.name, 'Azure Container Apps', 'Azure Database for PostgreSQL', 'Azure Key Vault', 'Azure Static Web Apps', 'Terraform', 'QuickBooks Online sandbox']

export const LEDE =
  'The accounts-payable desk of a fictional coffee roastery. Claude reads each supplier bill, code checks it against the purchase order, the delivery and the books, and a person approves before anything is paid. It runs on Microsoft Azure.'

const r = SITE.recorded
export const COST_RANGE = `$${r.cost_usd.min.toFixed(4)} to $${r.cost_usd.max.toFixed(4)}`
export const COST_TOTAL = `$${r.cost_usd.total.toFixed(2)}`
export const TESTS = SITE.tests.python.tests + SITE.tests.web.tests
export const TEST_FILES = SITE.tests.python.files + SITE.tests.web.files
export const BUILT = SITE.built
