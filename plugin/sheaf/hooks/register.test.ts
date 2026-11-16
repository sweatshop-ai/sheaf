import { expect, mock, test } from 'claude-code/testing'

const ORIGIN = 'https://chat.example.com'
const SESSION = '6f1c2f0e-3a55-4a0e-9d52-0c1f6a1b7d11'
const TELL = { id: 't1', doc: 'loose-bea/notes.md', thread: 'c1', message: 'Please look at this.', by: 'Cal', at: 'now' }

/** The engine beneath the mod, and a fake door behind `sheaf tells-poll`: every process the mod runs is answered from
 *  `door.answers` (a queue; the last one repeats, as a door re-lists a Tell until it is answered). */
function world($: any, on: any) {
  const clock = mock.clock(on)
  const door = { runs: [] as string[][], timeouts: [] as number[], failSubmits: 0, onPoll: null as null | ((argv: string[]) => void), failStore: false, holdSubmit: null as null | Promise<void>, holdStore: null as null | Promise<void>, answers: [{ exitCode: 0, stdout: '[]', stderr: '' }] as any[], session: SESSION, echo: undefined as string | undefined, helper: true,
                 printed: `${ORIGIN}/loose-bea/notes.md\non chat.example.com as Bea` }
  const submitted: string[] = []
  on('session.start', (_: any, e: any) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: door.session }))
  on('tool.call', (_: any, e: any) => String(e.tool).startsWith('mcp__')
    ? { result: { content: [] }, text: JSON.stringify({ id: 'c1', status: 'open', session: door.echo ?? door.session }) }     // the door's answer to a write names the id it recorded
    : { result: { stdout: door.printed, stderr: '' } })
  const lines: string[] = []
  on('ui.log', (_: any, e: any) => { lines.push(e.text); return { value: undefined } })
  const kept = new Map<string, unknown>()     // `$.store`, which outlives a session
  on('store.get', (_: any, e: any) => ({ value: kept.get(e.key) }))
  on('store.set', async (_: any, e: any) => {
    if (door.failStore && String(e.key).startsWith('delivered:')) throw new Error('disk full')
    const hold = door.holdStore      // the first write of what is kept is slow: it finishes after the ones called later
    if (hold && String(e.key).startsWith('delivered:')) { door.holdStore = null; await hold }
    kept.set(e.key, e.value)
    return { value: undefined }
  })
  on('session.end', (_: any, e: any) => ({ sessionId: e.sessionId }))
  on('turn.start', (_: any, e: any) => ({ turnId: e.turnId }))
  on('turn.complete', (_: any, e: any) => ({ text: e.answer }))
  on('process.run', (_: any, e: any) => {
    door.runs.push([...e.argv])
    if (e.argv[1] === 'headers') return { value: { exitCode: door.helper ? 0 : 1, stdout: '', stderr: '' } }     // `sheaf headers --check NAME`: does the entry carry the headersHelper
    door.timeouts.push(e.init?.timeoutMs)
    door.onPoll?.([...e.argv])
    return { value: door.answers.length > 1 ? door.answers.shift() : door.answers[0] }
  })
  on('prompt.submit', async (_: any, e: any) => {
    if (door.holdSubmit) await door.holdSubmit      // a submit resolves only when its turn ends
    if (door.failSubmits > 0 && e.origin?.kind !== 'composer') { door.failSubmits -= 1; throw new Error('refused') }
    submitted.push(e.text)
    return { text: e.text }
  })
  const send = () => $.tool.call({ tool: 'Bash', command: 'sheaf notes.md' })
  const mcp = (tool: string) => $.tool.call({ tool, id: 'c1', text: 'Looking.' } as any)
  return { clock, door, submitted, send, mcp, lines, kept }
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

test('a session id the session did not declare under is never polled: a fork gets nothing of its parent', async ($, on) => {
  const w = world($, on)
  w.door.answers = [{ exitCode: 0, stdout: JSON.stringify([TELL]), stderr: '' }]
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  await start($)
  await w.clock.advance(10_000)
  w.door.session = 'fork-session'
  await end($, 'answer')
  await w.clock.advance(60_000)
  expect(polls(w.door).some((r: string[]) => r[5] === 'fork-session')).toBe(false)
  expect(w.submitted.length).toBe(0)
})

test('a fork that only makes a door MCP write is armed, polls with its own id and gets its own Tell', async ($, on) => {
  const w = world($, on)
  w.door.session = 'fork-session'
  w.door.answers = [{ exitCode: 0, stdout: JSON.stringify([TELL]), stderr: '' }]
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.clock.advance(30_000)
  expect(polls(w.door).length).toBe(0)
  await w.mcp('mcp__sheaf-chat_example_com__reply')
  await w.clock.advance(1_000)
  expect(polls(w.door)[0]).toEqual(['sheaf', 'tells-poll', '--server', 'sheaf-chat_example_com', '--session', 'fork-session', '--wait', '25'])
  await w.clock.advance(6_000)
  expect(w.submitted.length).toBe(1)
})

test('a read of the door, and a tool of another server, arm nothing', async ($, on) => {
  const w = world($, on)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.mcp('mcp__sheaf-chat_example_com__read')
  await w.mcp('mcp__sheaf-chat_example_com__tells')
  await w.mcp('mcp__other__reply')
  await w.clock.advance(60_000)
  expect(polls(w.door).length).toBe(0)
})

test('the parent keeps its own Tell when a fork has declared itself apart: each id is polled for itself only', async ($, on) => {
  const w = world($, on)
  w.door.answers = [{ exitCode: 0, stdout: JSON.stringify([TELL]), stderr: '' }]
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  await w.clock.advance(6_000)
  expect(polls(w.door).every((r: string[]) => r[5] === SESSION)).toBe(true)
  expect(w.submitted.length).toBe(1)
  expect(w.submitted[0]).toContain('Please look at this.')
})

test('an answer that arrives after the session id changed is dropped: nothing is delivered and the Tell stays at the door', async ($, on) => {
  const w = world($, on)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  w.door.answers = [{ exitCode: 0, stdout: JSON.stringify([TELL]), stderr: '' }]
  w.door.onPoll = argv => { if (argv[5] === SESSION) w.door.session = 'new-session' }     // a /clear while the poll waits
  await w.clock.advance(1_000)
  await w.clock.advance(60_000)
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

const DOOR_KEY = `--origin ${ORIGIN}`      // how the mod names a tiroir in what it keeps
const listing = (...ids: string[]) => [{ exitCode: 0, stdout: JSON.stringify(ids.map(id => ({ ...TELL, id }))), stderr: '' }]
const armedBefore = (w: any, sent: Record<string, string[]>) => {
  w.kept.set(`doors:${SESSION}`, [{ flag: '--origin', value: ORIGIN }])      // what an earlier run of the mod stored for this session
  w.kept.set(`delivered:${SESSION}`, sent)
}

test('a resumed session does not submit again a Tell it submitted before and has not answered: the door still lists it', async ($, on) => {
  const w = world($, on)
  armedBefore(w, { [DOOR_KEY]: ['t1'] })
  w.door.answers = listing('t1')
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.clock.advance(20_000)
  expect(polls(w.door).length).toBeGreaterThan(0)
  expect(w.submitted.length).toBe(0)
  expect(w.kept.get(`delivered:${SESSION}`)).toEqual({ [DOOR_KEY]: ['t1'] })      // still listed, so still kept
})

test('a Tell the mod submits is kept for the session once its submit has succeeded', async ($, on) => {
  const w = world($, on)
  w.door.answers = listing('t1')
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  await w.clock.advance(1_000)
  expect(w.submitted.length).toBe(1)
  expect(w.kept.get(`delivered:${SESSION}`)).toEqual({ [DOOR_KEY]: ['t1'] })
})

test('a Tell whose submit was rejected is not kept, and is submitted and kept when a later submit succeeds', async ($, on) => {
  const w = world($, on)
  w.door.failSubmits = 1
  w.door.answers = listing('t1')
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  await w.clock.advance(1_000)
  expect(w.submitted.length).toBe(0)
  expect(w.kept.get(`delivered:${SESSION}`)).toEqual({})      // recorded when the submit started, taken back when it was rejected
  await w.clock.advance(20_000)
  expect(w.submitted.length).toBe(1)
  expect(w.kept.get(`delivered:${SESSION}`)).toEqual({ [DOOR_KEY]: ['t1'] })
})

test('a submit that succeeds when the store cannot be written still submits the Tell once: the cost is a repeat after a resume, never a lost Tell', async ($, on) => {
  const w = world($, on)
  w.door.failStore = true
  w.door.answers = listing('t1')
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  await w.clock.advance(30_000)
  expect(w.submitted.length).toBe(1)
  expect(w.kept.get(`delivered:${SESSION}`)).toBeUndefined()
})

test('a Tell is kept from the moment its submit starts: a resume during the Tell\'s own turn does not submit it again', async ($, on) => {
  const w = world($, on)
  let release!: () => void
  w.door.holdSubmit = new Promise<void>(r => { release = r })
  w.door.answers = listing('t1')
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  await w.clock.advance(1_000)
  expect(w.kept.get(`delivered:${SESSION}`)).toEqual({ [DOOR_KEY]: ['t1'] })      // the submit has not resolved
  release()
})

test('writes of what is kept finish in the order they were called: a slow older snapshot never overwrites a newer one', async ($, on) => {
  const w = world($, on)
  armedBefore(w, { [DOOR_KEY]: ['a'] })
  let release!: () => void
  w.door.holdStore = new Promise<void>(r => { release = r })
  w.door.answers = [...listing('a', 't1'), ...listing('t1')]      // t1 is submitted and kept; then the door stops listing a
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.clock.advance(1_000)
  expect(w.submitted.length).toBe(1)
  await w.clock.advance(12_000)      // the second poll prunes a: a newer snapshot, called while the first write is still open
  release()
  await w.clock.advance(1_000)
  expect(w.kept.get(`delivered:${SESSION}`)).toEqual({ [DOOR_KEY]: ['t1'] })
})

test('a Tell the door no longer lists is forgotten: the session answered it', async ($, on) => {
  const w = world($, on)
  armedBefore(w, { [DOOR_KEY]: ['t1', 'gone'] })
  w.door.answers = listing('t1')
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.clock.advance(2_000)
  expect(w.kept.get(`delivered:${SESSION}`)).toEqual({ [DOOR_KEY]: ['t1'] })
})

test('sixty kept Tells are all still kept and none is submitted again when a 61st is submitted: there is no small count cap', async ($, on) => {
  const w = world($, on)
  const old = Array.from({ length: 60 }, (_, i) => `old${i}`)
  armedBefore(w, { [DOOR_KEY]: old })
  w.door.answers = listing(...old, 't1')
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.clock.advance(20_000)
  expect(w.submitted.length).toBe(1)
  expect(w.kept.get(`delivered:${SESSION}`)).toEqual({ [DOOR_KEY]: [...old, 't1'] })
  w.door.answers = listing(...old, 't1')
  await w.clock.advance(30_000)
  expect(w.submitted.length).toBe(1)      // none of the sixty was submitted again
})

test('the poll is given longer than the CLI\'s own 35 s call', async ($, on) => {
  const w = world($, on)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  await w.clock.advance(1_000)
  expect(w.door.timeouts[0]).toBeGreaterThan(35_000)
})

test('a door MCP write arms the mod only when that server\'s entry carries the headersHelper', async ($, on) => {
  const w = world($, on)
  w.door.helper = false
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.mcp('mcp__sheaf-chat_example_com__reply')
  await w.clock.advance(30_000)
  expect(w.door.runs.some(r => r[1] === 'headers' && r[2] === '--check' && r[3] === 'sheaf-chat_example_com')).toBe(true)
  expect(polls(w.door).length).toBe(0)
  await w.send()                                  // a `sheaf X.md` send declares the session without the helper
  await w.clock.advance(1_000)
  expect(polls(w.door).length).toBe(1)
})

test('a session that writes to two tiroirs polls both, each with its own backoff', async ($, on) => {
  const w = world($, on)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  w.door.printed = 'https://second.example.com/loose-bea/notes.md\non second.example.com as Bea'
  await w.send()
  await w.clock.advance(1_000)
  const asked = polls(w.door).map((r: string[]) => `${r[2]} ${r[3]}`)
  expect(asked).toContain(`--origin ${ORIGIN}`)
  expect(asked).toContain('--origin https://second.example.com')
  await w.mcp('mcp__sheaf-third_example_com__reply')
  await w.clock.advance(6_000)
  expect(polls(w.door).map((r: string[]) => `${r[2]} ${r[3]}`)).toContain('--server sheaf-third_example_com')
})

test('a Tell of the second tiroir is delivered', async ($, on) => {
  const w = world($, on)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  w.door.printed = 'https://second.example.com/loose-bea/notes.md\non second.example.com as Bea'
  w.door.onPoll = argv => { if (argv[3] === 'https://second.example.com') w.door.answers = [{ exitCode: 0, stdout: JSON.stringify([TELL]), stderr: '' }] }
  await w.send()
  await w.clock.advance(1_000)
  await w.clock.advance(12_000)
  expect(w.submitted.length).toBe(1)
})

test('a re-armed session starts with no backoff from the session before', async ($, on) => {
  const w = world($, on)
  w.door.answers = [{ exitCode: 1, stdout: '', stderr: 'sheaf: down' }]
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  await w.clock.advance(80_000)                    // failures pile up: the gap is 20 s, then 40 s
  await $.session.end({ reason: 'clear', sessionId: SESSION, resume: {} } as any)
  w.door.session = 'new-session'
  w.door.answers = [{ exitCode: 0, stdout: '[]', stderr: '' }]
  await w.send()
  const before = polls(w.door).length
  await w.clock.advance(1_000)
  expect(polls(w.door).length).toBe(before + 1)
  expect(polls(w.door).at(-1)![5]).toBe('new-session')
})

test('a re-armed session is not held back by a Tell submitted for the session before', async ($, on) => {
  const w = world($, on)
  w.door.answers = [{ exitCode: 0, stdout: JSON.stringify([TELL]), stderr: '' }]
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.send()
  await w.clock.advance(1_000)
  expect(w.submitted.length).toBe(1)               // handed to submit; its turn never starts
  await $.session.end({ reason: 'clear', sessionId: SESSION, resume: {} } as any)
  w.door.session = 'new-session'
  w.door.answers = [{ exitCode: 0, stdout: JSON.stringify([TELL2]), stderr: '' }]
  await w.send()
  await w.clock.advance(7_000)                     // well inside the 60 s window of the first submit
  expect(w.submitted.length).toBe(2)
})

test('a door write arms only when the id the door recorded is the session\'s own; after a /clear it says so once and arms nothing', async ($, on) => {
  const w = world($, on)
  w.door.echo = 'old-session'          // the helper still sends the old id until the MCP reconnects
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.mcp('mcp__sheaf-chat_example_com__reply')
  await w.mcp('mcp__sheaf-chat_example_com__reply')
  await w.clock.advance(60_000)
  expect(polls(w.door).length).toBe(0)
  expect(w.lines.length).toBe(1)
  expect(w.lines[0]).toContain('/clear')
  w.door.echo = undefined              // the MCP reconnected: the door records the new id
  await w.mcp('mcp__sheaf-chat_example_com__reply')
  await w.clock.advance(1_000)
  expect(polls(w.door)[0]).toContain(SESSION)
})

test('a door write that echoes no id (an older door) arms nothing', async ($, on) => {
  const w = world($, on)
  w.door.echo = ''
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.mcp('mcp__sheaf-chat_example_com__reply')
  await w.clock.advance(60_000)
  expect(polls(w.door).length).toBe(0)
})

test('a new id that declares itself before the tick has left the old one is armed, not lost', async ($, on) => {
  const w = world($, on)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.mcp('mcp__sheaf-chat_example_com__reply')
  await w.clock.advance(1_000)
  w.door.session = 'cleared-session'
  await w.mcp('mcp__sheaf-third_example_com__reply')      // the same moment: no tick ran leave() yet
  await w.clock.advance(1_000)
  const mine = polls(w.door).filter((r: string[]) => r.includes('cleared-session'))
  expect(mine.length).toBeGreaterThan(0)
  expect(mine.every((r: string[]) => r.includes('sheaf-third_example_com'))).toBe(true)
})

test('an empty echo prints no /clear line', async ($, on) => {
  const w = world($, on)
  w.door.echo = ''
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await w.mcp('mcp__sheaf-chat_example_com__reply')
  expect(w.lines.length).toBe(0)
})

test('a stale write after a second /clear says so again: the line is once per session id', async ($, on) => {
  const w = world($, on)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  w.door.echo = 'old-1'
  await w.mcp('mcp__sheaf-chat_example_com__reply')
  await w.mcp('mcp__sheaf-chat_example_com__reply')
  expect(w.lines.length).toBe(1)
  w.door.session = 'second-session'       // a second /clear
  w.door.echo = 'second-old'
  await w.mcp('mcp__sheaf-chat_example_com__reply')
  await w.mcp('mcp__sheaf-chat_example_com__reply')
  expect(w.lines.length).toBe(2)
})
