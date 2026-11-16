import type { Register } from 'claude-code'
import { accept, followSession, fresh, nextGap, originOf, type Poller, POLL_TIMEOUT_MS, putBack, shouldPoll, takeNext, tellText, type Tell, WAIT_SECONDS } from './core'

/** One long-poll of the door for this session, through the laptop's own `sheaf tells-poll`, so the token stays in the
 *  keyring and never reaches this module. It prints a JSON array of Tells. */
async function poll($: any, origin: string, session: string): Promise<Tell[]> {
  const r = await $.process.run(['sheaf', 'tells-poll', '--origin', origin, '--session', session, '--wait', String(WAIT_SECONDS)],
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

/** One Tell per turn: while its turn runs, `running` holds the next one back. */
async function deliver($: any, m: Mod) {
  const p = m.p
  followSession(p, await $.session.id())     // a /clear since the poll: the held Tells were for the old id
  const t = takeNext(p, m.running === 0, m.interrupted, await $.clock.now())
  if (!t) return
  // A submit that fails keeps the Tell: the door lists it until the session answers it, and it is offered again.
  // Not awaited: a submit may resolve only when its turn ends, and this runs inside `turn.complete`.
  $.prompt.submit({ text: tellText(t) }).then((r: any) => { if (r?.drop !== undefined) putBack(p, t) }, () => putBack(p, t))
}

/** One tick: poll when due, then deliver what is held. */
async function tick($: any, m: Mod, origin: string) {
  const p = m.p
  if (!shouldPoll(p, await $.clock.now(), m.notBefore)) return deliver($, m)
  p.busy = true
  try {
    followSession(p, await $.session.id())
    accept(p, await poll($, origin, p.session))
    p.failures = 0
  } catch {
    p.failures += 1
  } finally {
    p.busy = false
    m.notBefore = (await $.clock.now()) + nextGap(p)
  }
  await deliver($, m)
}

/** Start polling `origin`: quiet until a send has named one. */
function arm($: any, m: Mod, origin: string) {
  m.p.origin = origin
  m.timer = $.clock.every(1000, () => tick($, m, origin))
}

/** Where a session that sent a page polls, kept by session id: a `claude --resume` of it arms the mod again. */
const originKey = (session: string) => `origin:${session}`

export const register: Register = (on) => {
  const m: Mod = { p: fresh(), running: 0, interrupted: false, notBefore: 0, timer: null }

  // Quiet until this session has sent a page: only a successful `sheaf FILE.md` that printed a tiroir address arms it.
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const done: any = await next(e)
    const command = String((e as any).command ?? '')
    const out = typeof done?.result?.stdout === 'string' ? done.result.stdout : ''
    if (/\bsheaf\s+\S+\.md\b/.test(command) && !m.p.origin) {
      const origin = originOf(out)
      if (origin) {
        arm($, m, origin)
        await $.store.set(originKey(await $.session.id()), origin)
      }
    }
    return done
  })

  // A session that sent a page and is resumed (`claude --resume`) keeps its id, so the door still queues for it.
  on('session.start', async ($, e, next) => {
    const origin = await $.store.get(originKey(await $.session.id()))
    if (typeof origin === 'string' && !m.p.origin) arm($, m, origin)
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
    m.timer?.cancel()
    m.timer = null
    m.p.origin = null
    return next(e)
  })
}
