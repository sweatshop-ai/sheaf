import { expect, test } from 'claude-code/testing'
import { fresh, nextGap, doorOfTool, originOf, shouldPoll, takeNext, tellText, MIN_GAP_MS, MAX_BACKOFF_MS } from './core'

test('no polling before the first send, and never two at once', async () => {
  const p = fresh()
  expect(shouldPoll(p, 1_000, 0)).toBe(false)
  p.origin = { flag: '--origin', value: 'https://chat.example.com' }
  expect(shouldPoll(p, 1_000, 0)).toBe(true)
  p.busy = true
  expect(shouldPoll(p, 1_000, 0)).toBe(false)
})

test('a failure backs the poll off, doubling to five minutes, and a success resets it', async () => {
  const p = fresh()
  expect(nextGap(p)).toBe(MIN_GAP_MS)
  p.failures = 1
  expect(nextGap(p)).toBe(2 * MIN_GAP_MS)
  p.failures = 30
  expect(nextGap(p)).toBe(MAX_BACKOFF_MS)
  p.origin = { flag: '--origin', value: 'https://chat.example.com' }
  expect(shouldPoll(p, 1_000, 5_000)).toBe(false)
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
