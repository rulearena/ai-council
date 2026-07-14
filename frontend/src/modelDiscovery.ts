export type DiscoveryResponse = { models: string[] }

export type DiscoveryEvent =
  | { type: 'started'; identity: string }
  | { type: 'succeeded'; identity: string; models: string[] }
  | { type: 'failed'; identity: string; error: unknown }
  | { type: 'settled'; identity: string }

export class LatestDiscoveryRequest {
  private generation = 0

  invalidate(): void {
    this.generation += 1
  }

  manualModelEdited(): void {
    this.invalidate()
  }

  async run(
    identity: string,
    load: () => Promise<DiscoveryResponse>,
    publish: (event: DiscoveryEvent) => void,
  ): Promise<void> {
    const generation = ++this.generation
    publish({ type: 'started', identity })
    try {
      const result = await load()
      if (generation !== this.generation) return
      publish({ type: 'succeeded', identity, models: result.models })
    } catch (error) {
      if (generation !== this.generation) return
      publish({ type: 'failed', identity, error })
    } finally {
      if (generation === this.generation) {
        publish({ type: 'settled', identity })
      }
    }
  }
}
