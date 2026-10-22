# ZT-4e832aab8822 -- users: Optimize check_can_access_user.

- lang: py   issue: #27835   tier: B
- fix: https://github.com/zulip/zulip/commit/4e832aab88224ebf1c426c01c53ecb8deea0cb26
- f2p: zerver.tests.test_users.GetProfileTest.test_check_can_access_user_for_a_spectator, zerver.tests.test_users.GetProfileTest.test_get_users_involved_in_dms_excludes_deactivated_users
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "performance optimization",
  "reason": "Real, plausibly-assigned optimization work with a deterministic outcome-based grader. The hidden tests assert database/memcached query counts via Django's query-counting assertions \u2014 the precise observable effect of the optimization (short-circuiting check_can_access_user for self-access and spectators eliminates a NamedUserGroup query) \u2014 and these fail-before/pass-after deterministically. It also adds a genuine behavioral assertion (check_can_access_user returns True for a spectator/None user_profile). Query-count assertions are established, deterministic practice in Zulip's test suite, not incidental format pinning; no exact-string snapshots, version gating, or migration internals are involved."
}

## screen: coupling
{
  "verdict": "clean",
  "required_contract": [],
  "reason": "The test binds no new names: check_can_access_user already exists at the base commit with a signature admitting None (the base code asserts user_profile is not None), and every other change merely decrements pre-existing database-query and memcached count assertions on existing user-visible flows. The asserted counts are the direct, implementation-independent consequence of the required behavior (self-access must short-circuit before any DB/cache access \u2014 a goal the base test itself flagged as a TODO), so any correct fix yields exactly these numbers without guessing author-specific names or internals."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue alone is thin (it discusses a broader optimization idea), but the expected-behavior evidence pins down a determinate, checkable outcome: check_can_access_user must short-circuit to True with zero DB/cache work for self-access and for a None (spectator) accessor, before any policy lookups, with correspondingly reduced query/cache counts in the calling flows. Two engineers given this brief would produce compatible implementations."
}
