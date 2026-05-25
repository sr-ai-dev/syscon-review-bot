# Spec Gate Files API Requirements

## Background

The review bot can receive GitHub diff paths in quoted and escaped form for non-ASCII file names. In that case, the local raw diff parser may fail to recover paths such as `spec/260521-기능통합/requirements.md`.

When the spec gate depends on parsed raw diff paths, a pull request that already contains valid spec files can be incorrectly blocked with "no spec document changes".

## Requirements

- When `require_spec_files` is enabled, spec gate validation must use GitHub's pull request file list as the source of changed file names.
- The gate must still block pull requests with no valid spec files.
- The gate must still block pull requests with only one required spec file in a spec directory.
- The gate must pass when a single `spec/<feature>/` directory contains at least two of:
  - `requirements.md`
  - `design.md`
  - `tasks.md`
- The existing 406 large-diff fallback must continue to reuse the file list it already fetched.
- The implementation must not change the prompt, model review, filtering, or review rendering behavior.

## Regression Case

For a pull request containing:

- `spec/260521-기능통합/requirements.md`
- `spec/260521-기능통합/tasks.md`

the spec gate must pass even if the raw diff header encodes the path as quoted octal escape sequences.
