import {defineConfig} from '@playwright/test'
import config from './playwright.mock.config'

/** Fleet data runs against isolated mock instances and real Python services. */
export default defineConfig({...config,
  testMatch: ['**/fleet-data-workflow.spec.ts', '**/mind-fleet-ledger.spec.ts',
    '**/mind-fleet-tech.spec.ts', '**/mind-calculator.spec.ts', '**/mind-navigation.spec.ts'],
  timeout: 120000, expect: {timeout: 15000},
  use: {...config.use, actionTimeout: 20000},
})
