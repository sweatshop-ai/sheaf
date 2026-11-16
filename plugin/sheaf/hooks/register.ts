import type { Register } from 'claude-code'
import { fresh, nextGap, originOf, shouldPoll, takeNext, tellText, type Tell, WAIT_SECONDS } from './core'

/** One long-poll of the door for this session, through the laptop's own `sheaf tells-poll` (not built yet: ticket 19, open
 *  decision 1), so the token stays in the keyring and never reaches this module. It prints a JSON array of Tells. */
async function poll($: any, origin: string, session: string): Promise<Tell[]> {
  const r = await $.process.run(['sheaf', 'tells-poll', '--origin', origin, '--session', session, '--wait', String(WAIT_SECONDS)],
    { timeoutMs: (WAIT_SECONDS + 5) * 1000 })
  if (r.exitCode !== 0) throw new Error(r.stderr)
  return JSON.parse(r.stdout) as Tell[]
}

export const register: Register = (on) => {
  const p = fresh()
  let session = ''
  let interrupted = false
  let notBefore = 0
  let stop: (() => void) | null = null

  on('session.start', async ($, e, next) => {
    session = (e as any).sessionId ?? ''
    return next(e)
  })

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
          if (!shouldPoll(p, await $.clock.now(), notBefore)) return
          p.busy = true
          try {
            p.held.push(...(await poll($, origin, session)))
            p.failures = 0
          } catch {
            p.failures += 1
          } finally {
            p.busy = false
            notBefore = (await $.clock.now()) + nextGap(p)
          }
          const t = takeNext(p, true, interrupted)
          if (t) void $.prompt.submit({ text: tellText(t) })
        }
        stop = $.clock.every(1000, tick)
      }
    }
    return done
  })

  // Esc keeps the Tell: nothing is submitted until the member types again.
  on('turn.complete', async ($, e, next) => {
    if ((e as any).reason === 'aborted') interrupted = true
    return next(e)
  })
  on('prompt.submit', async ($, e, next) => {
    if ((e as any).origin?.kind === 'composer') interrupted = false
    return next(e)
  })
  on('session.end', async ($, e, next) => {
    stop?.()
    return next(e)
  })
}
