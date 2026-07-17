import assert from 'node:assert/strict'
import test from 'node:test'

import { waitForSettledProjection } from '../../src/meetingSettlement.ts'

type Projection = {
  id: string
  activity_status: 'running' | 'completed'
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

test('settlement polling skips running projections and returns the first settled projection', async () => {
  const responses: Projection[] = [
    { id: 'partial-1', activity_status: 'running' },
    { id: 'partial-2', activity_status: 'running' },
    { id: 'settled', activity_status: 'completed' },
  ]
  const loaded: string[] = []

  const result = await waitForSettledProjection({
    load: async () => {
      const response = responses.shift()!
      loaded.push(response.id)
      return response
    },
    wait: async () => undefined,
    isCurrent: () => true,
  })

  assert.equal(result?.id, 'settled')
  assert.deepEqual(loaded, ['partial-1', 'partial-2', 'settled'])
})

test('an older late settlement refresh cannot publish after a newer refresh wins', async () => {
  const older = deferred<Projection>()
  let generation = 0
  const start = (load: () => Promise<Projection>) => {
    const requestGeneration = ++generation
    return waitForSettledProjection({
      load,
      wait: async () => undefined,
      isCurrent: () => requestGeneration === generation,
    })
  }

  const olderResult = start(() => older.promise)
  const newerResult = start(async () => ({ id: 'newer', activity_status: 'completed' }))

  assert.equal((await newerResult)?.id, 'newer')
  older.resolve({ id: 'older-stale', activity_status: 'completed' })
  assert.equal(await olderResult, null)
})
