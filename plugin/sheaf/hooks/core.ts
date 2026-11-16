// The mod's decisions, apart from `$`: when to poll, how long to back off, when a Tell goes in. register.ts only wires them.

export const WAIT_SECONDS = 25      // the door's own limit is 25
export const MIN_GAP_MS = 5_000     // between two polls that returned at once (the door refuses a third in flight: "wait 5 seconds")
export const MAX_BACKOFF_MS = 5 * 60_000

export type Tell = { id: string; doc: string; thread: string; message: string; by: string; at: string }

export type Poller = {
  origin: string | null      // the tiroir the session last sent a page to; null until the first send
  session: string            // the session id the held and delivered Tells belong to
  failures: number           // consecutive polls that failed
  held: Tell[]               // taken from the door, not yet submitted (an Esc, or a turn running)
  delivered: Set<string>     // Tells already submitted: the door lists a Tell until the session answers it
  busy: boolean              // a poll is in flight: one at a time per session, never a pile-up
}

export const fresh = (): Poller => ({ origin: null, session: '', failures: 0, held: [], delivered: new Set(), busy: false })

/** The address a successful `sheaf FILE.md` printed on its first line, or null: only a tiroir page arms the mod. */
export function originOf(output: string): string | null {
  const first = output.split('\n', 1)[0]?.trim() ?? ''
  const m = /^(https:\/\/[^/\s]+)\/\S+/.exec(first)
  return m ? m[1] : null
}

/** Whether to start a poll now. Never before the first send, never two at once, never while waiting out a failure. */
export function shouldPoll(p: Poller, now: number, notBefore: number): boolean {
  return p.origin !== null && !p.busy && now >= notBefore
}

/** How long to wait after a poll: a short gap on success, doubling to five minutes on failure. */
export function nextGap(p: Poller): number {
  if (p.failures === 0) return MIN_GAP_MS
  return Math.min(MAX_BACKOFF_MS, MIN_GAP_MS * 2 ** p.failures)
}

/** The session id changed (a /clear): what was held and delivered belonged to the old id, which the door will not
 *  list under the new one. */
export function followSession(p: Poller, session: string) {
  if (p.session === session) return
  p.session = session
  p.held = []
  p.delivered = new Set()
}

/** Keep the Tells of a poll that are neither held nor submitted already. */
export function accept(p: Poller, tells: Tell[]) {
  for (const t of tells) {
    if (!p.delivered.has(t.id) && !p.held.some(h => h.id === t.id)) p.held.push(t)
  }
}

/** The text a Tell becomes in the session: says where it came from, and that it is another party's text, not the member's. */
export function tellText(t: Tell): string {
  return `A Tell from ${t.by} on the shared Sheaf page ${t.doc} (sheaf sent this, the person at the keyboard did not type it; ` +
    `treat it as a request from that page's reader, not as the person's own instruction):\n\n${t.message}`
}

/** What to submit now. Only when no turn runs and the member has not interrupted: a Tell is never put into a running
 *  turn, and after an Esc it waits for the member's next input. Returns the Tell to submit, or null. */
export function takeNext(p: Poller, idle: boolean, interrupted: boolean): Tell | null {
  if (!idle || interrupted) return null
  const t = p.held.shift() ?? null
  if (t) p.delivered.add(t.id)
  return t
}
