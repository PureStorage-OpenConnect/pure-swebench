# Bucket IPv6 addresses by network prefix for rate limiting

## Background

Zulip rate-limits unauthenticated and per-IP traffic using the `RateLimitedIPAddr` class (see `zerver/lib/rate_limiter.py`). Each client IP address currently gets its own rate-limit bucket, keyed as:

```
RateLimitedIPAddr:<{ip_address}>:{domain}
```

where `domain` is the rate-limit domain (e.g. `api_by_ip`).

This per-address scheme is effectively useless against IPv6 clients: an IPv6 user is typically delegated at least a /64 (2^64 addresses), so an abuser can trivially bypass the limit by rotating to an adjacent address within their own subnet. Rate limiting for IPv6 should therefore be applied to the containing network, not the individual address.

## Required behavior

1. **IPv6 addresses are bucketed by network prefix.** When the client address is IPv6, the rate-limit bucket must be the containing network at a configurable prefix length (default /64), rather than the single address. Consequences:
   - Two IPv6 addresses inside the same /N network must produce the *same* bucket key (and thus share a rate limit). Example: `2001:0db8:ce1:12::8a2e:0370` and `2001:0db8:ce1:12::8a2e:045f` share a bucket at prefix 64.
   - Two IPv6 addresses in *different* /N networks must produce different bucket keys. Example: `2001:0db8:ce1:12::8a2e:0370` and `2001:0db8:ce1:13::8a2e:045f` must not share a bucket at prefix 64.

2. **Key format.** The overall key format is unchanged: `RateLimitedIPAddr:<{addr}>:{domain}`. For IPv4, `{addr}` remains the full literal address, e.g. `RateLimitedIPAddr:<192.168.0.123>:api_by_ip`. For IPv6, `{addr}` is the network in canonical compressed CIDR notation per RFC 5952, as produced by Python's standard `ipaddress` formatting — leading zeros dropped and `::` compression applied. For example, address `2001:0db8::ce1:12:8a2e:0370` at prefix 64 yields the key `RateLimitedIPAddr:<2001:db8::/64>:api_by_ip` (note the `0db8` group is rendered as `db8`). The same address at prefix 56 yields `RateLimitedIPAddr:<2001:db8::/56>:api_by_ip`, and at prefix 48 yields `RateLimitedIPAddr:<2001:db8::/48>:api_by_ip`.

3. **Configurable prefix length.** The prefix length must be a parameter rather than hard-coded, defaulting to 64. Only /64 is used in production for now, but the parameter must correctly handle other prefix lengths (e.g. 56 and 48) so larger buckets can be layered on later, per the motivating design: additional, slightly-larger limits at the /48 and /32 levels are anticipated.

4. **IPv4 behavior is unchanged.** IPv4 addresses keep per-address bucketing and their existing key format. The prefix parameter must not affect IPv4 keys.

5. **Backend selection is unaffected by address family.** IPv6 addresses must work on the Tornado in-memory rate-limiting path exactly as IPv4 does. Whether a `RateLimitedIPAddr` uses the Tornado in-memory backend or the Redis backend must continue to depend only on whether the process is running inside Tornado and whether the domain is in the set of domains handled in-process (e.g. `api_by_ip` uses the in-memory backend under Tornado; other domains fall back to Redis) — never on whether the address is IPv4 or IPv6. Constructing a `RateLimitedIPAddr` with an IPv6 address such as `2002:DB8::21f:5bff:febf:ce22:1111` must not raise or degrade to a different backend.

## Interface requirements

- `RateLimitedIPAddr` gains an optional keyword parameter `ipv6_network_prefix: int = 64` that selects the IPv6 subnet prefix length used for rate-limit bucketing. Only /64 is used in production, but the parameter must accept and correctly apply other prefixes such as 56 and 48.
- For an IPv6 client address, the rate-limit bucket is the containing network at the configured prefix, not the individual address: two IPv6 addresses within the same /N network must map to the same bucket key, and addresses in different /N networks must map to different keys.
- The bucket-key format is unchanged: `RateLimitedIPAddr:<{addr}>:{domain}`, where the angle-bracketed portion is the full address for IPv4 and the network for IPv6.
- The IPv6 network in the key is rendered in canonical compressed CIDR form per RFC 5952 as produced by standard IP formatting (leading zeros omitted, `::` compression), e.g. address `2001:0db8::ce1:12:8a2e:0370` at prefix 64 yields `2001:db8::/64`.
- IPv4 addresses keep their existing per-address bucketing and key format, e.g. `RateLimitedIPAddr:<192.168.0.123>:api_by_ip`.
- IPv6 addresses must be accepted for the Tornado in-memory rate-limiting path identically to IPv4: backend selection (Tornado in-memory vs Redis) depends only on the domain setting, not on address family.

## Acceptance criteria

- `RateLimitedIPAddr("192.168.0.123", domain="api_by_ip").key()` returns `RateLimitedIPAddr:<192.168.0.123>:api_by_ip`.
- `RateLimitedIPAddr("2001:0db8::ce1:12:8a2e:0370", domain="api_by_ip", ipv6_network_prefix=64).key()` returns `RateLimitedIPAddr:<2001:db8::/64>:api_by_ip`; with `ipv6_network_prefix=56` it returns `RateLimitedIPAddr:<2001:db8::/56>:api_by_ip`; with `ipv6_network_prefix=48` it returns `RateLimitedIPAddr:<2001:db8::/48>:api_by_ip`.
- Same-subnet IPv6 addresses collide to one key; different-subnet IPv6 addresses do not, at each supported prefix length.
- Under Tornado, a `RateLimitedIPAddr` built from either an IPv4 or an IPv6 address selects the Tornado in-memory backend for an in-process domain like `api_by_ip`, and the Redis backend for any other domain.
