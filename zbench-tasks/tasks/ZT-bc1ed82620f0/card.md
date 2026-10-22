# ZT-bc1ed82620f0 -- rate_limiter: Block IPv6 by /64 instead of per-single-IP.

- lang: py   issue: #21544   tier: B
- fix: https://github.com/zulip/zulip/commit/bc1ed82620f008c2784372717926f16b31ca7fb1
- f2p: zerver.tests.test_rate_limiter.RateLimitedObjectsTest.test_ip_bucket_key
- p2p: (none)

## screen: suitability
{
  "verdict": "keep",
  "task_type": "behavior-change (security improvement to rate limiting)",
  "reason": "Real, plausibly-assigned engineering task: change IPv6 rate-limit bucketing from per-address to per-/64 subnet. The hidden test grades observable behavior deterministically \u2014 same-subnet addresses must map to the same bucket key, different subnets to different keys \u2014 with fail-before/pass-after semantics (pre-change, two IPs in one /64 produce different keys). The exact-key assertions are short, deterministic strings that ARE the behavior under test (the Redis bucket key), derived from Python's stable ipaddress canonicalization, not incidental formatting or a long snapshot. No time/version gating, no migration or schema bookkeeping."
}

## screen: coupling
{
  "verdict": "specifiable",
  "required_contract": [
    "RateLimitedIPAddr gains an optional keyword parameter `ipv6_network_prefix: int = 64` that selects the IPv6 subnet prefix length used for rate-limit bucketing (only /64 is used in production, but the parameter must accept other prefixes such as 56 and 48).",
    "For an IPv6 client address, the rate-limit bucket is the containing network at the configured prefix, not the individual address: two IPv6 addresses within the same /N network must map to the same bucket key, and addresses in different /N networks must map to different keys.",
    "The bucket-key format is unchanged: `RateLimitedIPAddr:<{addr}>:{domain}`, where the angle-bracketed portion is the full address for IPv4 and the network for IPv6.",
    "The IPv6 network in the key is rendered in canonical compressed CIDR form per RFC 5952 as produced by standard IP formatting (leading zeros omitted, `::` compression), e.g. address 2001:0db8::ce1:12:8a2e:0370 at prefix 64 yields `2001:db8::/64`.",
    "IPv4 addresses keep their existing per-address bucketing and key format, e.g. `RateLimitedIPAddr:<192.168.0.123>:api_by_ip`.",
    "IPv6 addresses must be accepted for the Tornado in-memory rate-limiting path identically to IPv4: backend selection (Tornado in-memory vs Redis) depends only on the domain setting, not on address family."
  ],
  "reason": "Most assertions go through interfaces that already exist at the base commit (RateLimitedIPAddr's constructor with ip_addr/domain, its .key() method, and the pre-existing `ClassName:<ip>:domain` key format \u2014 the IPv4 key assertion and the Tornado backend-selection test would pass unchanged). The new surface the test binds to is narrow: the `ipv6_network_prefix` keyword parameter with default 64, and the IPv6 bucketing semantics where the key embeds the canonical compressed network string. RateLimitedIPAddr is the rate-limiter library's entry point used across the codebase, and its bucket keys are operator-visible Redis keys, so a ticket could legitimately pin both the parameter name/default and the exact key rendering. The exact strings asserted (e.g. `2001:db8::/64` with the leading zero dropped) follow standard RFC 5952 formatting rather than an author-invented encoding, so a solver handed the contract above would be graded on correctness, not name-guessing. Nothing binds to private helpers, mocks of internals, or internal module layout \u2014 the `tor-exit-node` special case in the fix is not asserted by the test."
}

## screen: statement
{
  "sufficient": true,
  "why": "The issue states the motivation and target design (bucket IPv6 by /64), and the expected-behavior evidence pins down the exact observable contract: the ipv6_network_prefix parameter with default 64, the exact key format and RFC 5952 canonical rendering, same/different-subnet collision semantics at prefixes 64/56/48, unchanged IPv4 keys, and address-family-independent backend selection. Together these make the outcome determinate and independently checkable."
}
