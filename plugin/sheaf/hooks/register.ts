import type { Register } from 'claude-code'
import { accept, followSession, fresh, nextGap, originOf, type Poller, shouldPoll, takeNext, tellText, type Tell, WAIT_SECONDS } from './core'

/** One long-poll of the door for this session, through the laptop's own `sheaf tells-poll`, so the token stays in the
 *  keyring and never reaches this module. It prints a JSON array of Tells. */
async function poll($: any, origin: string, session: string): Promise<Tell[]> {
  const r = await $.process.run(['sheaf', 'tells-poll', '--origin', origin, '--session', session, '--wait', String(WAIT_SECONDS)],
    { timeoutMs: (WAIT_SECONDS + 5) * 1000 })
  if (r.exitCode !== 0) throw new Error(r.stderr)
  const got = JSON.parse(r.stdout)
  if (!Array.isArray(got)) throw new Error('tells-poll printed no list')
  return got as Tell[]
}

/** One Tell per turn: when it starts a turn, `running` holds the next one back until that turn ends. */
async function deliver($: any, p: Poller, idle: boolean, interrupted: boolean) {
  followSession(p, await $.session.id())     // a /clear since the poll: the held Tells were for the old id
  const t = takeNext(p, idle, interrupted)
  if (t) void $.prompt.submit({ text: tellText(t) })
}

export const register: Register = (on) => {
  const p = fresh()
  let running = 0              // main-loop turns under way
  let interrupted = false      // the member pressed Esc: nothing goes in until they type again
  let notBefore = 0
  let stop: (() => void) | null = null

  // Quiet until this session has sent a page: only a successful `sheaf FILE.md` that printed a tiroir address arms it.
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const done: any = await next(e)
    const command = String((e as any).command ?? '')
    const out = typeof done?.result?.stdout === 'string' ? done.result.stdout : ''
    if (/\bsheaf\s+\S+\.md\b/.test(command) && !p.origin) {
      const origin = originOf(out)
      if (origin) {
        p.origin = origin
        const tick = async () => {
          if (!shouldPoll(p, await $.clock.now(), notBefore)) return deliver($, p, running === 0, interrupted)
          p.busy = true
          try {
            followSession(p, await $.session.id())
            accept(p, await poll($, origin, p.session))
            p.failures = 0
          } catch {
            p.failures += 1
          } finally {
            p.busy = false
            notBefore = (await $.clock.now()) + nextGap(p)
          }
          await deliver($, p, running === 0, interrupted)
        }
        stop = $.clock.every(1000, tick)
      }
    }
    return done
  })

  on('turn.start', async ($, e, next) => {
    if (!(e as any).agentId) running += 1
    return next(e)
  })
  // Esc keeps the Tell: nothing is submitted until the member types again.
  on('turn.complete', async ($, e, next) => {
    if (!(e as any).agentId) {
      running = Math.max(0, running - 1)
      if ((e as any).reason === 'aborted') interrupted = true
    }
    const done = await next(e)
    await deliver($, p, running === 0, interrupted)
    return done
  })
  on('prompt.submit', async ($, e, next) => {
    if ((e as any).origin?.kind !== 'composer') return next(e)
    interrupted = false      // what is held goes in at the next tick, or when this input's turn ends (never from here: a submit from a submit hook waits on itself)
    return next(e)
  })
  on('session.end', async ($, e, next) => {
    stop?.()
    return next(e)
  })
}
