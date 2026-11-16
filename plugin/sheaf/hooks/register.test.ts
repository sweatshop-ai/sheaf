import { expect, mock, test } from 'claude-code/testing'

const ORIGIN = 'https://chat.example.com'
const SESSION = '6f1c2f0e-3a55-4a0e-9d52-0c1f6a1b7d11'
const TELL = { id: 't1', doc: 'loose-bea/notes.md', thread: 'c1', message: 'Please look at this.', by: 'Cal', at: 'now' }

/** The engine beneath the mod, and a fake door behind `sheaf tells-poll`: every process the mod runs is answered from
 *  `door.answers` (a queue; the last one repeats, as a door re-lists a Tell until it is answered). */
function world($: any, on: any) {
  const clock = mock.clock(on)
  const door = { runs: [] as string[][], timeouts: [] as number[], failSubmits: 0, answers: [{ exitCode: 0, stdout: '[]', stderr: '' }] as any[], session: SESSION,
                 printed: `${ORIGIN}/loose-bea/notes.md\non chat.example.com as Bea` }
  const submitted: string[] = []
  on('session.start', (_: any, e: any) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: door.session }))
  on('tool.call', () => ({ result: { stdout: door.printed, stderr: '' } }))
  const kept = new Map<string, unknown>()     // `$.store`, which outlives a session
  on('store.get', (_: any, e: any) => ({ value: kept.get(e.key) }))
  on('store.set', (_: any, e: any) => { kept.set(e.key, e.value); return { value: undefined } })
  on('session.end', (_: any, e: any) => ({ sessionId: e.sessionId }))
  on('turn.start', (_: any, e: any) => ({ turnId: e.turnId }))
  on('turn.complete', (_: any, e: any) => ({ text: e.answer }))
  on('process.run', (_: any, e: any) => {
    door.runs.push([...e.argv])
    door.timeouts.push(e.init?.timeoutMs)
    return { value: door.answers.length > 1 ? door.answers.shift() : door.answers[0] }
  })
  on('prompt.submit', (_: any, e: any) => {
    if (door.failSubmits > 0 && e.origin?.kind !== 'composer') { door.failSubmits -= 1; throw new Error('refused') }
    submitted.push(e.text)
    return { text: e.text }
  })
  const send = () => $.tool.call({ tool: 'Bash', command: 'sheaf notes.md' })
  return { clock, door, submitted, send }
}

const start = ($: any) => $.turn.start({ text: '', turnId: 'a' })
const end = ($: any, reason: string) => $.turn.complete({ reason, answer: '', durationMs: 1, isAborted: reason === 'aborted', turnId: 'a' })
const polls = (door: any) => door.runs.filter((r: string[]) => r[1] === 'tells-poll')

test('no polling before the first send; after it, one poll with the origin and this session', async ($, on) => {
  const w = world($, on)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.clock.advance(60_000)
  expect(polls(w.door).length).toBe(0)
  await w.send()
  await w.clock.advance(1_000)
  expect(polls(w.door)[0]).toEqual(['sheaf', 'tells-poll', '--origin', ORIGIN, '--session', SESSION, '--wait', '25'])
})

test('a send that is not a tiroir page arms nothing', async ($, on) => {
  const w = world($, on)
  w.door.printed = 'http://127.0.0.1:27419/root/notes.md'
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  await w.clock.advance(60_000)
  expect(polls(w.door).length).toBe(0)
})

test('a Tell is submitted once, with where it came from, though the door lists it again', async ($, on) => {
  const w = world($, on)
  w.door.answers = [{ exitCode: 0, stdout: JSON.stringify([TELL]), stderr: '' }]
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  await w.clock.advance(1_000)
  await w.clock.advance(30_000)
  expect(polls(w.door).length).toBeGreaterThan(1)
  expect(w.submitted.length).toBe(1)
  expect(w.submitted[0]).toContain('Please look at this.')
  expect(w.submitted[0]).toContain('did not type')
  expect(w.submitted[0]).toContain('Cal')
})

test('never mid-turn: a Tell taken during a turn waits for the turn to end', async ($, on) => {
  const w = world($, on)
  w.door.answers = [{ exitCode: 0, stdout: JSON.stringify([TELL]), stderr: '' }]
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  await start($)
  await w.clock.advance(10_000)
  expect(w.submitted.length).toBe(0)
  await end($, 'answer')
  await w.clock.advance(6_000)
  expect(w.submitted.length).toBe(1)
})

test('Esc keeps the Tell, and it arrives with the member\'s next input', async ($, on) => {
  const w = world($, on)
  w.door.answers = [{ exitCode: 0, stdout: JSON.stringify([TELL]), stderr: '' }]
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  await start($)
  await w.clock.advance(10_000)
  await end($, 'aborted')
  await w.clock.advance(30_000)
  expect(w.submitted.length).toBe(0)
  await $.prompt.submit({ text: 'carry on', wait: false, origin: { kind: 'composer' } } as any)
  await w.clock.advance(6_000)
  expect(w.submitted.filter(t => t.includes('Please look at this.')).length).toBe(1)
})

test('a failing poll backs off: the next one is not before 10 s, then 20 s', async ($, on) => {
  const w = world($, on)
  w.door.answers = [{ exitCode: 1, stdout: '', stderr: 'sheaf: no credential' }]
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  await w.clock.advance(1_000)
  expect(polls(w.door).length).toBe(1)
  await w.clock.advance(9_000)
  expect(polls(w.door).length).toBe(1)
  await w.clock.advance(2_000)
  expect(polls(w.door).length).toBe(2)
  await w.clock.advance(18_000)
  expect(polls(w.door).length).toBe(2)
  await w.clock.advance(2_000)
  expect(polls(w.door).length).toBe(3)
})

test('a new session id (after /clear) polls under it and drops what was held for the old one', async ($, on) => {
  const w = world($, on)
  w.door.answers = [{ exitCode: 0, stdout: JSON.stringify([TELL]), stderr: '' }]
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  await start($)
  await w.clock.advance(10_000)
  w.door.session = 'new-session'
  w.door.answers = [{ exitCode: 0, stdout: '[]', stderr: '' }]
  await end($, 'answer')
  await w.clock.advance(20_000)
  expect(polls(w.door).at(-1)![5]).toBe('new-session')
  expect(w.submitted.length).toBe(0)
})

test('the token is never in what the mod runs', async ($, on) => {
  const w = world($, on)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  await w.clock.advance(1_000)
  expect(JSON.stringify(w.door.runs)).not.toMatch(/token|Bearer|Authorization/i)
})

const TELL2 = { ...TELL, id: 't2', message: 'And this one.' }

test('two Tells are never submitted at once: the second waits for the first one\'s turn to start and end', async ($, on) => {
  const w = world($, on)
  w.door.answers = [{ exitCode: 0, stdout: JSON.stringify([TELL, TELL2]), stderr: '' }]
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  await w.clock.advance(20_000)
  expect(w.submitted.length).toBe(1)
  await start($)
  await w.clock.advance(10_000)
  expect(w.submitted.length).toBe(1)
  await end($, 'answer')
  await w.clock.advance(6_000)
  expect(w.submitted.length).toBe(2)
  expect(w.submitted[1]).toContain('And this one.')
})

test('a submit that fails keeps the Tell: it is offered again', async ($, on) => {
  const w = world($, on)
  w.door.failSubmits = 1
  w.door.answers = [{ exitCode: 0, stdout: JSON.stringify([TELL]), stderr: '' }]
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  await w.clock.advance(20_000)
  expect(w.submitted.length).toBe(1)
  expect(w.submitted[0]).toContain('Please look at this.')
})

test('a session that ended and sends a page again is polled again', async ($, on) => {
  const w = world($, on)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  await w.clock.advance(1_000)
  expect(polls(w.door).length).toBe(1)
  await $.session.end({ reason: 'clear', sessionId: SESSION, resume: {} } as any)
  const before = polls(w.door).length
  await w.clock.advance(30_000)
  expect(polls(w.door).length).toBe(before)
  w.door.session = 'new-session'
  await w.send()
  await w.clock.advance(1_000)
  expect(polls(w.door).at(-1)![5]).toBe('new-session')
})

test('a session resumed after it sent a page is polled without a new send', async ($, on) => {
  const w = world($, on)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  await $.session.end({ reason: 'other', sessionId: SESSION, resume: {} } as any)
  const before = polls(w.door).length
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.clock.advance(2_000)
  expect(polls(w.door).length).toBeGreaterThan(before)
})

test('the poll is given longer than the CLI\'s own 35 s call', async ($, on) => {
  const w = world($, on)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  await w.clock.advance(1_000)
  expect(w.door.timeouts[0]).toBeGreaterThan(35_000)
})
