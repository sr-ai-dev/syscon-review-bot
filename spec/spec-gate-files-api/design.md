# Spec Gate Files API Design

## Approach

The review engine already fetches the PR diff for prompt construction. That diff remains the source for changed patches and review context.

For spec gate validation only, the engine uses the GitHub pull request files API and checks each item's `filename` value. GitHub returns decoded repository paths there, so non-ASCII spec paths are available in normal `spec/<feature>/...` form.

## Flow

1. Load PR metadata and repository review config.
2. Fetch the raw PR diff and parse it into `FileDiff` objects.
3. If the raw diff is too large and GitHub returns 406, fetch the PR files API and build `FileDiff` objects from that response.
4. If `require_spec_files` is disabled, skip spec gate validation.
5. If `require_spec_files` is enabled:
   - reuse the PR files API response from the 406 fallback when present;
   - otherwise fetch the PR files API;
   - run `check_spec_files()` on the API `filename` values.
6. If the gate fails, submit the existing spec gate review and stop.
7. If the gate passes, continue with filtering, hunk expansion, prompt construction, and model review.

## Non-Goals

- Do not teach the raw diff parser to decode every quoted Git path format.
- Do not alter spec gate rules.
- Do not alter ignored file filtering.
- Do not make extra GitHub API calls when spec gate validation is disabled.

## Test Strategy

- Keep existing spec gate block/pass tests.
- Add a regression test where the raw diff contains escaped non-ASCII spec paths, while the files API contains decoded `spec/...` paths.
- Verify the regression test reaches model review instead of submitting a spec gate block review.
