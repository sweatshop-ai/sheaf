import { expect, test } from 'claude-code/testing'
import { addDoor, fresh, nextGap, doorOfTool, originOf, shouldPoll, takeNext, tellText, MIN_GAP_MS, MAX_BACKOFF_MS } from './core'

const CHAT = { flag: '--origin', value: 'https://chat.example.com' } as const

test('no polling before the first send, and never two polls of one door at once', async () => {
  const p = fresh()
  expect(p.doors.length).toBe(0)
  const d = addDoor(p, CHAT)!
  expect(shouldPoll(d, 1_000)).toBe(true)
  d.busy = true
  expect(shouldPoll(d, 1_000)).toBe(false)
})

test('a failure backs the door off, doubling to five minutes, and the wait is kept per door', async () => {
  const p = fresh()
  const d = addDoor(p, CHAT)!
  expect(nextGap(d)).toBe(MIN_GAP_MS)
  d.failures = 1
  expect(nextGap(d)).toBe(2 * MIN_GAP_MS)
  d.failures = 30
  expect(nextGap(d)).toBe(MAX_BACKOFF_MS)
  d.notBefore = 5_000
  expect(shouldPoll(d, 1_000)).toBe(false)
  const other = addDoor(p, { flag: '--origin', value: 'https://second.example.com' })!
  expect(shouldPoll(other, 1_000)).toBe(true)
})

test('a tiroir is added once; a second tiroir is added beside it', async () => {
  const p = fresh()
  expect(addDoor(p, CHAT)).not.toBeNull()
  expect(addDoor(p, { ...CHAT })).toBeNull()
  expect(addDoor(p, { flag: '--server', value: 'sheaf-second_example_com' })).not.toBeNull()
  expect(p.doors.length).toBe(2)
})

test('a Tell is submitted when idle, never mid-turn, and after an Esc it waits', async () => {
  const p = fresh()
  p.held.push({ id: 'a', doc: 'x/y.md', thread: 'c1', message: 'hello', by: 'Bea', at: 'now' })
  expect(takeNext(p, false, false, 0)).toBeNull()
  expect(takeNext(p, true, true, 0)).toBeNull()
  expect(p.held.length).toBe(1)
  expect(takeNext(p, true, false, 0)?.id).toBe('a')
  expect(p.held.length).toBe(0)
})

test('the session reads where a Tell came from', async () => {
  const text = tellText({ id: 'a', doc: 'x/y.md', thread: 'c1', message: 'hello', by: 'Bea', at: 'now' })
  expect(text).toContain('Bea')
  expect(text).toContain('x/y.md')
  expect(text).toContain('did not type')
})

test('only a tiroir address printed by a send arms the mod', async () => {
  expect(originOf('https://chat.example.com/loose-bea/2026-11/notes.md\non chat.example.com as Bea')).toEqual({ flag: '--origin', value: 'https://chat.example.com' })
  expect(originOf('  ~ http://127.0.0.1:27419/root/notes.md')).toBeNull()
  expect(originOf('')).toBeNull()
})

test('a write through the door\'s MCP server declares the session; a read or another server does not', async () => {
  for (const w of ['create', 'update', 'reply', 'resolve'])
    expect(doorOfTool(`mcp__sheaf-chat_example_com__${w}`)).toEqual({ flag: '--server', value: 'sheaf-chat_example_com' })
  for (const t of ['mcp__sheaf-chat_example_com__read', 'mcp__sheaf-chat_example_com__tells', 'mcp__other__reply', 'Bash', 'reply'])
    expect(doorOfTool(t)).toBeNull()
})
