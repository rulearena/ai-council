export type SettlementProjection = {
  activity_status: string
}

export type SettlementPollOptions<T extends SettlementProjection> = {
  load: () => Promise<T>
  wait: () => Promise<void>
  isCurrent: () => boolean
  maxAttempts?: number
}

export async function waitForSettledProjection<T extends SettlementProjection>(
  options: SettlementPollOptions<T>,
): Promise<T | null> {
  const maxAttempts = options.maxAttempts ?? 3600
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    await options.wait()
    if (!options.isCurrent()) return null
    const projection = await options.load()
    if (!options.isCurrent()) return null
    if (projection.activity_status === 'running') continue
    return projection
  }
  return null
}
