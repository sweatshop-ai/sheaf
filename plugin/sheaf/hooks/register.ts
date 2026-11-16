// The Sheaf mod: delivers the Tells of the shared Sheaf into this laptop session (SPEC 9.14).
//
// Arming rule: a Tell is addressed to the session id that declared itself on a door write (SPEC 9.8), so this module
// arms the moment this session declares itself, by any route: a Bash `sheaf FILE.md` that printed a tiroir address, or a
// create, update, reply or resolve of the door's MCP server whose entry carries the headersHelper (`sheaf headers`, which
// sends X-Sheaf-Session; without it the door never learns the id, so that write arms nothing; and only when the door's answer echoes the id it
// recorded and that is the session's own, which after a /clear is not so until the MCP reconnects). A fork has an id of its
// own and arms itself that way; it is never armed because its parent was, and it never polls with the parent's id. Every
// tiroir the session declared itself to is polled, for that one id, each with its own backoff. The poller is armed for
// one id: when the session id is another one it stops and forgets its tiroirs, backoff and Tell in flight, and an answer
// that arrives for an id that is no longer the session's is dropped, so its Tells wait at the door for that id.
import type { Register } from 'claude-code'
import { accept, addDoor, type Door, doorKey, type DoorState, doorOfTool, echoedSession, fresh, nextGap, originOf, type Poller, POLL_TIMEOUT_MS, pruneStored, putBack, shouldPoll, storedByDoor, takeNext, tellText, type Tell, WAIT_SECONDS } from './core'

/** One long-poll of the door for this session, through the laptop's own `sheaf tells-poll`, so the token stays in the
 *  keyring and never reaches this module. It prints a JSON array of Tells. */
async function poll($: any, door: Door, session: string): Promise<Tell[]> {
  const r = await $.process.run(['sheaf', 'tells-poll', door.flag, door.value, '--session', session, '--wait', String(WAIT_SECONDS)],
    { timeoutMs: POLL_TIMEOUT_MS })
  if (r.exitCode !== 0) throw new Error(r.stderr)
  const got = JSON.parse(r.stdout)
  if (!Array.isArray(got)) throw new Error('tells-poll printed no list')
  return got as Tell[]
}

/** What the mod keeps between events, for one session. */
type Mod = {
  p: Poller
  running: number            // main-loop turns under way
  interrupted: boolean       // the member pressed Esc: nothing goes in until they type again
  timer: { cancel: () => void } | null
  saidFor: string            // the session id the line was said under
  saidStale: boolean         // the one line about a write recorded under an id that is no longer the session's
}

/** The session id changed under the poller (a fork, a /clear that raised no end): this poller declared itself for one id
 *  only, so it stops, and what it held was for that id. */
function leave(m: Mod) {
  m.timer?.cancel()
  m.timer = null
  m.p.doors = []
  m.p.armedFor = ''
  m.p.held = []
  m.p.stored.clear()      // what is kept belongs to the id that left; a resume of it reads it back
  m.p.submittingUntil = 0      // a re-armed session has no Tell in flight; each door's backoff went with its state
}

/** What is kept for a session that is resumed (`claude --resume`): the Tells whose submit succeeded and that the door
 *  still lists. The door lists a Tell until the session answers it, and a resumed session has the submitted Tell in its
 *  transcript already. A write that fails costs a resume one repeated Tell, never a lost one. */
const deliveredKey = (session: string) => `delivered:${session}`

async function keepDelivered($: any, m: Mod, session: string) {
  if (m.p.armedFor !== session) return      // the poller left the session meanwhile
  await $.store.set(deliveredKey(session), storedByDoor(m.p)).catch(() => {})
}

/** One Tell per turn: while its turn runs, `running` holds the next one back. */
async function deliver($: any, m: Mod) {
  const p = m.p
  if (!p.doors.length) return
  if ((await $.session.id()) !== p.armedFor) return leave(m)
  const t = takeNext(p, m.running === 0, m.interrupted, await $.clock.now())
  if (!t) return
  // A submit that fails keeps the Tell: the door lists it until the session answers it, and it is offered again.
  // It is recorded for a resume only once its submit has succeeded.
  // Not awaited: a submit may resolve only when its turn ends, and this runs inside `turn.complete`.
  const session = p.armedFor
  $.prompt.submit({ text: tellText(t) }).then(async (r: any) => {
    if (r?.drop !== undefined) return putBack(p, t)
    if (p.armedFor !== session || !t.door) return
    p.stored.set(t.id, t.door)
    await keepDelivered($, m, session)
  }, () => putBack(p, t))
}

/** One poll of one door, for the session id it is made under. An answer that arrives when the session is another is
 *  dropped: the Tell stays at the door for the id it was queued for. */
async function pollDoor($: any, m: Mod, d: DoorState) {
  const p = m.p
  const id = await $.session.id()
  if (id !== p.armedFor) return leave(m)
  d.busy = true
  try {
    const tells = await poll($, d.door, id)
    if ((await $.session.id()) === id && p.doors.includes(d)) {
      const key = doorKey(d.door)
      accept(p, tells, key)
      if (pruneStored(p, key, tells)) await keepDelivered($, m, id)
    }
    d.failures = 0
  } catch {
    d.failures += 1
  } finally {
    d.busy = false
    d.notBefore = (await $.clock.now()) + nextGap(d)
  }
}

/** One tick: poll each door that is due, then deliver what is held. */
async function tick($: any, m: Mod) {
  const now = await $.clock.now()
  const due = m.p.doors.filter(d => shouldPoll(d, now))
  if (!due.length) return deliver($, m)
  await Promise.all(due.map(d => pollDoor($, m, d)))
  await deliver($, m)
}

/** Start polling for the session that has just declared itself and for no other id: the first tiroir starts the timer,
 *  a later one is polled by the same timer. */
async function arm($: any, m: Mod, door: Door) {
  if (!addDoor(m.p, door)) return false
  if (!m.timer) {
    m.p.armedFor = await $.session.id()
    m.p.session = m.p.armedFor
    m.timer = $.clock.every(1000, () => tick($, m))
  }
  return true
}

/** Where a session that sent a page polls, kept by session id: a `claude --resume` of it arms the mod again. */
const doorsKey = (session: string) => `doors:${session}`

const isDoor = (d: any): d is Door => d && (d.flag === '--origin' || d.flag === '--server') && typeof d.value === 'string'

/** A door MCP write declares the session only when that server's entry sends the headersHelper's headers: without them
 *  the door never learns the id, and the mod would poll for a session no Tell was queued for. `sheaf headers --check`
 *  reads the entry (the mod never reads `.claude.json`). */
async function sendsSession($: any, door: Door): Promise<boolean> {
  const r = await $.process.run(['sheaf', 'headers', '--check', door.value], { timeoutMs: 10_000 }).catch(() => null)
  return r?.exitCode === 0
}

/** A session declares itself, by any route, each time it writes through a tiroir's door: a `sheaf FILE.md` that printed
 *  that tiroir's address, or a create, update, reply or resolve of the door's MCP server (when its entry has the
 *  headersHelper). Tells are addressed to the session id that declared itself, so a fork (an id of its own) arms itself
 *  that way and never inherits its parent's door or id; every tiroir it declared to is polled, for that one id. Quiet
 *  until then. */
async function declare($: any, m: Mod, door: Door | null) {
  if (!door) return
  if (m.p.doors.length && (await $.session.id()) !== m.p.armedFor) leave(m)      // the tick has not run yet: this id declares itself now, so it is armed, not dropped
  if (m.p.doors.some(d => d.door.flag === door.flag && d.door.value === door.value)) return
  if (!(await arm($, m, door))) return
  await $.store.set(doorsKey(m.p.armedFor), m.p.doors.map(d => d.door))
}

export const register: Register = (on) => {
  const m: Mod = { p: fresh(), running: 0, interrupted: false, timer: null, saidFor: '', saidStale: false }

  on('tool.call', async ($, e, next) => {
    const door = doorOfTool(String((e as any).tool))
    const done: any = await next(e)
    if (door && done?.isError !== true && (await sendsSession($, door))) {
      // Arm only for the id the door recorded. After a /clear the helper still sends the old id until the MCP reconnects:
      // that write queues Tells for the old id, which nobody polls, so it arms nothing (SPEC 9.14).
      const id = await $.session.id()
      const echoed = echoedSession(done)
      if (id !== m.saidFor) m.saidStale = false      // a new session id (a second /clear) may be told again
      if (echoed === id) await declare($, m, door)
      else if (echoed && !m.saidStale) {      // an empty echo (an older door) is no stale write: nothing to say
        m.saidStale = true
        m.saidFor = id
        await $.ui.log('Sheaf: this write was recorded under the session before /clear, so Tells from the page are not delivered here yet. They wait at the door; reconnect the sheaf MCP server (/mcp) and write again.')
      }
    }
    return done
  })
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const done: any = await next(e)
    const command = String((e as any).command ?? '')
    const out = typeof done?.result?.stdout === 'string' ? done.result.stdout : ''
    if (/\bsheaf\s+\S+\.md\b/.test(command)) await declare($, m, originOf(out))
    return done
  })

  // A session that declared itself and is resumed (`claude --resume`) keeps its id, so the door still queues for it.
  on('session.start', async ($, e, next) => {
    const id = await $.session.id()
    const doors: any = await $.store.get(doorsKey(id))
    const sent: any = await $.store.get(deliveredKey(id))
    if (sent && typeof sent === 'object' && !Array.isArray(sent)) {
      for (const [key, ids] of Object.entries(sent)) if (Array.isArray(ids)) for (const t of ids) if (typeof t === 'string') { m.p.delivered.add(t); m.p.stored.set(t, key) }
    }
    if (Array.isArray(doors) && !m.p.doors.length) for (const door of doors) if (isDoor(door)) await arm($, m, door)
    return next(e)
  })

  on('turn.start', async ($, e, next) => {
    if (!(e as any).agentId) {
      m.running += 1
      m.p.submittingUntil = 0      // the Tell's turn has started: `running` holds the next one back from here
    }
    return next(e)
  })
  // Esc keeps the Tell: nothing is submitted until the member types again.
  on('turn.complete', async ($, e, next) => {
    if (!(e as any).agentId) {
      m.running = Math.max(0, m.running - 1)
      if ((e as any).reason === 'aborted') m.interrupted = true
    }
    const done = await next(e)
    await deliver($, m)
    return done
  })
  on('prompt.submit', async ($, e, next) => {
    if ((e as any).origin?.kind !== 'composer') return next(e)
    m.interrupted = false      // what is held goes in at the next tick, or when this input's turn ends (never from here: a submit from a submit hook waits on itself)
    return next(e)
  })
  // The session ends (or is /cleared): stop the timer and forget the origin, so the next send arms it again.
  on('session.end', async ($, e, next) => {
    leave(m)
    return next(e)
  })
}
