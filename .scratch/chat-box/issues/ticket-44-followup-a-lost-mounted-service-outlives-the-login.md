# 44b: A mounted 'gone' kept in sessionStorage outlives an expired login and a change of user

**What to build:** Since PR #305 (ticket 44, decision b) a mounted page's dictation-off state lives in `sessionStorage` (`sheaf-mount:rd-dict-off`). 'gone' covers a 401, a 404 and any network failure (SPEC 10.4), so one moment offline, or an expired login followed by signing in again in the same tab, leaves dictation off until the tab closes; a 403 for user A also holds for user B who signs in in that tab. Decide: keep as is (SPEC says "for the session"), store only 'denied' and let 'gone' stay per mount, or clear the key on a sign-in. Class a (Opus review of #305, finding 2, left open by design).

**Blocked by:** none

**Status:** ready-for-agent
