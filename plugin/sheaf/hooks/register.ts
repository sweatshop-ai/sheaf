// The Sheaf mod: delivers the Tells of the shared Sheaf into this laptop session (SPEC 9.14).
//
// Arming rule: a Tell is addressed to the session id that declared itself on a door write (SPEC 9.8), so this module
// arms the moment this session declares itself, by any route: a Bash `sheaf FILE.md` that printed a tiroir address, or a
// create, update, reply or resolve of the door's MCP server (the one the headersHelper sends X-Sheaf-Session on). A fork
// has an id of its own and arms itself that way; it is never armed because its parent was, and it never polls with the
// parent's id. The poller is armed for one id: when the session id is another one it stops, and an answer that arrives
// for an id that is no longer the session's is dropped, so its Tells wait at the door for that id.
import type { Register } from 'claude-code'
import { accept, type Door, doorOfTool, followSession, fresh, nextGap, originOf, type Poller, POLL_TIMEOUT_MS, putBack, shouldPoll, takeNext, tellText, type Tell, WAIT_SECONDS } from './core'

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
  notBefore: number          // no poll before this time
  timer: { cancel: () => void } | null
}

/** The session id changed under the poller (a fork, a /clear that raised no end): this poller declared itself for one id
 *  only, so it stops, and what it held was for that id. */
function leave(m: Mod) {
  m.timer?.cancel()
  m.timer = null
  m.p.origin = null
  m.p.armedFor = ''
  m.p.held = []
}

/** One Tell per turn: while its turn runs, `running` holds the next one back. */
async function deliver($: any, m: Mod) {
  const p = m.p
  if (!p.origin) return
  if ((await $.session.id()) !== p.armedFor) return leave(m)
  const t = takeNext(p, m.running === 0, m.interrupted, await $.clock.now())
  if (!t) return
  // A submit that fails keeps the Tell: the door lists it until the session answers it, and it is offered again.
  // Not awaited: a submit may resolve only when its turn ends, and this runs inside `turn.complete`.
  $.prompt.submit({ text: tellText(t) }).then((r: any) => { if (r?.drop !== undefined) putBack(p, t) }, () => putBack(p, t))
}

/** One tick: poll when due, then deliver what is held. Each poll is for the session id it was made under, and an
 *  answer that arrives when the session is another is dropped: the Tell stays at the door for the id it was queued for. */
async function tick($: any, m: Mod, door: Door) {
  const p = m.p
  if (!shouldPoll(p, await $.clock.now(), m.notBefore)) return deliver($, m)
  const id = await $.session.id()
  if (id !== p.armedFor) return leave(m)
  p.busy = true
  try {
    const tells = await poll($, door, id)
    if ((await $.session.id()) === id) accept(p, tells)
    p.failures = 0
  } catch {
    p.failures += 1
  } finally {
    p.busy = false
    m.notBefore = (await $.clock.now()) + nextGap(p)
  }
  await deliver($, m)
}

/** Start polling `door`, for the session that has just declared itself and for no other id. */
async function arm($: any, m: Mod, door: Door) {
  m.p.origin = door
  m.p.armedFor = await $.session.id()
  m.p.session = m.p.armedFor
  m.timer = $.clock.every(1000, () => tick($, m, door))
}

/** Where a session that sent a page polls, kept by session id: a `claude --resume` of it arms the mod again. */
const doorKey = (session: string) => `door:${session}`

/** A session declares itself, by any route, the first time it writes through the door: a `sheaf FILE.md` that printed a
 *  tiroir address, or a create, update, reply or resolve of the door's MCP server. Tells are addressed to the session id
 *  that declared itself, so a fork (an id of its own) arms itself that way and never inherits its parent's door or id:
 *  the poller polls for the one id it armed under. Quiet until then. */
async function declare($: any, m: Mod, door: Door | null) {
  if (!door || m.p.origin) return
  await arm($, m, door)
  await $.store.set(doorKey(m.p.armedFor), door)
}

export const register: Register = (on) => {
  const m: Mod = { p: fresh(), running: 0, interrupted: false, notBefore: 0, timer: null }

  on('tool.call', async ($, e, next) => {
    const door = doorOfTool(String((e as any).tool))
    const done: any = await next(e)
    if (door && done?.isError !== true) await declare($, m, door)
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
    const door: any = await $.store.get(doorKey(await $.session.id()))
    if (door && (door.flag === '--origin' || door.flag === '--server') && typeof door.value === 'string' && !m.p.origin) await arm($, m, door)
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
