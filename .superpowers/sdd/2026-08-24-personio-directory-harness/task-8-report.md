# Task 8 implementation report

Base: `056fec5`

## Implemented offline scope

- Extended the Harness acceptance matrix with exact tool contracts for pure
  Personio, pure RAG and mixed retrieval.
- Added explicit coverage for directory filters, normal and explicit
  onboarding visibility, all three coworker cascade levels, no-result behavior,
  pending access and stale sync disclosure.
- Replaced real-person prompts in the reusable matrix with clearly synthetic
  test prompts.
- Extended the deterministic report with case contracts and privacy-safe
  per-case results.
- Added hard failures when a pure directory case calls RAG or a mixed case does
  not call both adapters.
- Restricted stored case results to case ID, model ID, expected and actual
  tools, intent, evidence status, source kinds, validation status, latency and
  approved boolean assertions.
- Added an operations runbook for fresh-PowerShell preflight, read-only probe,
  local startup, aggregate state checks, the 14 interactive scenarios and
  production variable names.
- Updated the Harness audit to distinguish the historical RAG-only report from
  the new Personio release gate.

## TDD evidence

Initial focused run after adding the new contracts:

```text
4 failed, 4 passed
```

The failures were the intended missing-matrix, missing-contract and
privacy-safe result behaviors. After the minimal implementation:

```text
11 passed in 0.04s
```

The privacy regression injects explicit PII marker values into question,
answer, contact, Personio-ID, assertion-key and raw-evidence positions. None is
present in the generated report. A second red-green cycle verifies that
untrusted case, model and profile identifiers are normalized rather than
persisted.

## Review fix round 1

The review regressions first failed as intended:

```text
2 failed, 9 passed
```

After the matrix trust boundary and fail-closed exit gate were implemented,
the focused suite reported `11 passed in 0.04s`.

- The versioned matrix is now the sole source of expected models, allowed
  profiles and required case IDs.
- External payload fields with those names are ignored and cannot reduce or
  extend coverage.
- Empty, unavailable, unauthorized or incomplete coverage returns a non-zero
  release-gate exit code.
- Coverage values and reason suffixes come only from validated matrix IDs and
  fixed enums.
- Malicious model, profile and case markers are removed from results and
  reasons.
- The privacy test now injects a concrete synthetic phone number in addition
  to the existing PII markers.

## Fresh offline verification

```text
stack/personio-directory/tests: 89 passed in 0.92s
stack/tests: 423 passed in 5.62s
stack/kb-admin-api/tests: 188 passed in 52.66s
stack/kb-sync/tests: 13 passed in 1.37s
```

Python compilation, JSON parsing and `git diff --check` also completed with
exit code 0.

## Live-schema fix

A separately executed read-only probe reported the sanitized safe code
`personio_response_invalid`; no response body or employee value was retained.
The current v2 API envelope uses `_data` and places pagination below
`_meta.links.next`. The regression tests first failed as intended:

```text
4 failed, 14 passed
```

The client now accepts both the current envelope and the already supported
`data` / `links.next` shape. A nested `next.href` object and a direct string
cursor are supported, while malformed cursor objects and cursor URLs on a
foreign host are still rejected. Separate employment responses accept `_data`
as well. An incomplete but valid v2 assessment falls back to v1 without
returning sampled employee values.

After the minimal parser change, the focused client suite reported `18 passed`
and the full Personio service suite reported `72 passed`. This fix did not
read environment variables, call Personio or start the local service.

## Live-schema fix review round 1

The blank-cursor regressions first failed as intended:

```text
4 failed, 18 passed
```

Both the direct `links.next` form and nested `_meta.links.next.href` now accept
only a non-blank string or `None`. Empty and whitespace-only strings fail with
the sanitized `personio_response_invalid` code before pagination can terminate
or cursor-host validation begins. Valid legacy and current cursor forms remain
covered by the successful pagination tests.

After the guard was added, the focused client suite reported `22 passed`, the
full Personio service suite `76 passed` and the stack suite `423 passed`. No
environment variable or live endpoint was accessed.

## V1 authentication fix

A separately executed read-only probe next returned only the sanitized code
`personio_http_404` at the configured v1 authentication URL. The official v1
reference specifies `POST /v1/auth`, while v2 continues to use
`POST /v2/auth/token` with a form-urlencoded client-credentials body:

- https://developer.personio.de/v1.0/reference/post_auth
- https://developer.personio.de/reference/post_v2-auth-token

The auth regressions and corrected URL expectation first failed as intended:

```text
3 failed, 24 passed
```

The token parser now keeps the versions separate. V2 accepts only the OAuth
top-level `access_token` / `expires_in` shape. V1 accepts only the current
`data` envelope containing `token` and an optional `expires_in`. When v1 omits
the expiry, the client uses the documented 24-hour stable-token lifetime and
still refreshes five minutes early. The lifetime is established by Personio's
v1 authentication documentation:

- https://developer.personio.de/v1.0/reference/auth

Synthetic negative tests prove that the wrong version's envelope is rejected,
the safe error does not contain the response token or client secret, and
credentials remain in the POST body rather than query parameters. After the
minimal change, the focused config/client suite reported `27 passed`, the full
Personio service suite `79 passed` and the stack suite `423 passed`. This fix
did not read environment variables or call Personio.

## V1 authentication review round 1

The nested-expiry regressions first failed as intended:

```text
10 failed, 25 passed
```

V1 now reads `expires_in` only from the same nested `data` object as `token`.
If the nested field is absent, the v1-only 86,400-second default applies. If it
is present, it must be a finite positive integer or float; booleans, zero,
negative values, strings, `null`, NaN and infinity fail with the sanitized
`personio_auth_response_invalid` code. A top-level v1 `expires_in` is ignored
and cannot override either the nested value or the documented default. V2
parsing remains unchanged.

After the minimal correction, the focused client suite reported `35 passed`,
the full Personio service suite `89 passed` and the stack suite `423 passed`.
No environment variable or live endpoint was accessed.

## Explicitly pending

- Windows process-variable presence check in a newly opened PowerShell
- successful read-only Personio API probe after the schema fix
- controlled local Personio sync and aggregate Qdrant count comparison
- interactive user, admin and pending acceptance under `localhost:3004`

These steps were not attempted. The current Codex process had previously not
inherited the two Windows variables, and this task was explicitly restricted
from reading them or accessing the live API. No Personio secret, employee value
or live response was read, printed or persisted.

## Preferred-name and employment-type override

The user-approved 26 August domain decision replaces the earlier split-name
and internal-only assumptions. The first focused policy cycle failed with
`3 failed, 11 passed`; after extending the contract across API assessment,
sync, index and search, the broader red run reported `23 failed, 64 passed`.

The implementation now requires `Name (preferred)` as the sole human-name
mapping. It normalizes whitespace, uses the final token as `last_name`, uses
all preceding tokens as `first_name`, and rejects blank, single-token or
malformed names. Split first/last fields and employment type are no longer API
requirements. Raw employment type is not inspected by the API adapter, probe,
policy, sync, index or search code, so synthetic `EXTERNAL` records follow the
same path as internal records. A focused probe regression failed before that
last legacy access was removed and passed afterwards. `Last modified` remains
required for delta sync.

Fresh offline verification after the minimal implementation:

```text
stack/personio-directory/tests: 100 passed in 0.98s
stack/tests: 421 passed, 2 failed in 5.69s
```

The two stack failures are the unchanged worktree infrastructure gaps already
present at baseline: missing unversioned local files
`deploy/activate-kahle-open-webui-wissensportal-20260813.sh` and
`stack/.env.production.example`. Neither file was copied or created, and the
failures are unrelated to the Personio feature. No live API, environment
variable or local Compose service was accessed.

## Preferred-name review fix round 1

The real v1 change field is exposed as key `last_modified_at` with label
`Last modified at`. Its mapping regression first failed with the sanitized
required-fields error and then passed after both actual aliases were added.

The sync regressions for missing, blank, non-string, single-token and malformed
preferred names initially reported `8 failed, 1 passed`. Such records are now
explicitly ineligible: delta sync physically removes an existing point, and a
full sync no longer preserves it as temporarily malformed. The passing control
case confirms that another transiently malformed business field still retains
the last valid indexed record.

Fresh offline verification:

```text
stack/personio-directory/tests: 111 passed in 1.32s
stack/tests: 421 passed, 2 failed in 5.80s
```

The two stack failures remain the same missing unversioned local reference
files documented above. No live API, environment variable or Compose service
was accessed.

## Business-phone live-label fix

A sanitized live mapping assessment showed only the business phone unresolved.
The safe Personio label is `Telefonnummer geschäftlich`. The exact Unicode
label regression failed first with the required-fields error and passed after
the alias was added. Existing phone aliases remain supported. An explicit
UTF-8 code-point check confirmed that both production code and regression use
the real `ä` character rather than the terminal replacement glyph.

Fresh offline verification:

```text
stack/personio-directory/tests: 112 passed in 1.34s
stack/tests: 421 passed, 2 failed in 5.80s
```

The two stack failures remain the known missing unversioned local reference
files. No live API, environment variable or Compose service was accessed.
