import { afterEach, beforeEach, expect, vi, type MockInstance } from 'vitest'

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input
  if (input instanceof URL) return input.href
  return input.url
}

/**
 * Fails the test on any request that reaches `fetch`. Component tests mock the
 * API client. A request that slips past the mocks goes to the jsdom origin and
 * can settle after the test has ended. Its continuation then runs on the stores
 * of that test, and every store action it calls makes that test's Pinia the
 * active one again (Pinia sets the active instance in each action wrapper).
 *
 * `respond` answers requests the test expects on purpose. The guard answers
 * everything else with 501, a status the client does not retry.
 */
export function guardNetwork(respond: (url: string) => Response | undefined = () => undefined): void {
  const unmocked: string[] = []
  let fetchSpy: MockInstance<typeof fetch> | null = null

  beforeEach(() => {
    unmocked.length = 0
    fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = requestUrl(input)
      const response = respond(url)
      if (response) return response
      unmocked.push(url)
      return new Response(null, { status: 501, statusText: 'Not mocked in this test' })
    })
  })

  afterEach(() => {
    fetchSpy?.mockRestore()
    fetchSpy = null
    expect(unmocked, 'requests that bypassed the mocked API client').toEqual([])
  })
}
