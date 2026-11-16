import { expect, test } from 'claude-code/testing'
import { fresh, nextGap, originOf, shouldPoll, takeNext, tellText, MIN_GAP_MS, MAX_BACKOFF_MS } from './core'

test('no polling before the first send, and never two at once', async () => {
  const p = fresh()
  expect(shouldPoll(p, 1_000, 0)).toBe(false)
  p.origin = 'https://chat.example.com'
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
  p.origin = 'https://chat.example.com'
  expect(shouldPoll(p, 1_000, 5_000)).toBe(false)
})

test('a Tell is submitted when idle, never mid-turn, and after an Esc it waits', async () => {
  const p = fresh()
  p.held.push({ id: 'a', doc: 'x/y.md', message: 'hello', from: 'Bea' })
  expect(takeNext(p, false, false)).toBeNull()
  expect(takeNext(p, true, true)).toBeNull()
  expect(p.held.length).toBe(1)
  expect(takeNext(p, true, false)?.id).toBe('a')
  expect(p.held.length).toBe(0)
})

test('the session reads where a Tell came from', async () => {
  const text = tellText({ id: 'a', doc: 'x/y.md', message: 'hello', from: 'Bea' })
  expect(text).toContain('Bea')
  expect(text).toContain('x/y.md')
  expect(text).toContain('did not type')
})

test('only a tiroir address printed by a send arms the mod', async () => {
  expect(originOf('https://chat.example.com/loose-bea/2026-11/notes.md\non chat.example.com as Bea')).toBe('https://chat.example.com')
  expect(originOf('  ~ http://127.0.0.1:27419/root/notes.md')).toBeNull()
  expect(originOf('')).toBeNull()
})
