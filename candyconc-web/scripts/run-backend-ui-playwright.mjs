#!/usr/bin/env node
import { spawn } from 'node:child_process'
import process from 'node:process'

const executable = process.platform === 'win32' ? 'playwright.cmd' : 'playwright'
const args = ['test', 'e2e/backend-ui-live-smoke.spec.ts', '--project=chromium', ...process.argv.slice(2)]

const child = spawn(executable, args, {
  cwd: process.cwd(),
  env: {
    ...process.env,
    CANDYCONC_LIVE_BACKEND_SMOKE: '1',
  },
  stdio: 'inherit',
  shell: process.platform === 'win32',
})

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal)
    return
  }
  process.exit(code ?? 1)
})

child.on('error', (error) => {
  console.error(error)
  process.exit(1)
})
