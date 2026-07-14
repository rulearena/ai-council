import assert from 'node:assert/strict'
import test from 'node:test'

import {
  LatestDiscoveryRequest,
  type DiscoveryEvent,
} from '../../src/modelDiscovery.ts'

type Deferred<T> = {
  promise: Promise<T>
  resolve: (value: T) => void
  reject: (reason: unknown) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve
    reject = onReject
  })
  return { promise, resolve, reject }
}

test('invalidated discovery success, empty result, and error cannot update current state', async () => {
  for (const completion of ['success', 'empty', 'error'] as const) {
    const coordinator = new LatestDiscoveryRequest()
    const pending = deferred<{ models: string[] }>()
    const events: DiscoveryEvent[] = []
    const run = coordinator.run(
      'create|openai',
      () => pending.promise,
      (event) => events.push(event),
    )

    coordinator.invalidate()
    if (completion === 'success') pending.resolve({ models: ['gpt-current'] })
    if (completion === 'empty') pending.resolve({ models: [] })
    if (completion === 'error') pending.reject(new Error('old provider failed'))
    await run

    assert.deepEqual(events, [{ type: 'started', identity: 'create|openai' }])
  }
})

test('a newer request is the only request allowed to publish completion events', async () => {
  const coordinator = new LatestDiscoveryRequest()
  const oldRequest = deferred<{ models: string[] }>()
  const currentRequest = deferred<{ models: string[] }>()
  const events: DiscoveryEvent[] = []
  const publish = (event: DiscoveryEvent) => events.push(event)

  const oldRun = coordinator.run('create|openai', () => oldRequest.promise, publish)
  const currentRun = coordinator.run('create|custom', () => currentRequest.promise, publish)
  currentRequest.resolve({ models: ['current-model'] })
  await currentRun
  oldRequest.reject(new Error('late old failure'))
  await oldRun

  assert.deepEqual(events, [
    { type: 'started', identity: 'create|openai' },
    { type: 'started', identity: 'create|custom' },
    { type: 'succeeded', identity: 'create|custom', models: ['current-model'] },
    { type: 'settled', identity: 'create|custom' },
  ])
})

test('manual exact model edits invalidate late discovery success, empty result, and error', async () => {
  for (const completion of ['success', 'empty', 'error'] as const) {
    const coordinator = new LatestDiscoveryRequest()
    const pending = deferred<{ models: string[] }>()
    const events: DiscoveryEvent[] = []
    const run = coordinator.run(
      'create|openai|before-manual-edit',
      () => pending.promise,
      (event) => events.push(event),
    )

    // This is the public seam used when the user types an exact model ID while
    // discovery is still in flight. Their explicit choice supersedes the request.
    coordinator.manualModelEdited()
    if (completion === 'success') pending.resolve({ models: ['late-discovered-model'] })
    if (completion === 'empty') pending.resolve({ models: [] })
    if (completion === 'error') pending.reject(new Error('late provider error'))
    await run

    assert.deepEqual(events, [
      { type: 'started', identity: 'create|openai|before-manual-edit' },
    ])
  }
})
