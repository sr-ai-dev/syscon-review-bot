# Spec Gate Files API Tasks

## Completed

- [x] Changed spec gate validation to use GitHub PR files API `filename` values when `require_spec_files` is enabled.
- [x] Reused the existing PR files API response in the 406 fallback path.
- [x] Updated test GitHub mocks to provide realistic PR file metadata.
- [x] Added a regression test for escaped non-ASCII spec paths in raw diff headers.
- [x] Verified PR #265's actual file list passes `check_spec_files()`.
- [x] Verified raw diff parsing still misses the escaped spec paths, proving the regression covers the original failure mode.

## Verification

- [x] `.venv/bin/python -m pytest tests/test_engine.py tests/test_spec_check.py`
- [x] `.venv/bin/python -m pytest`

## Notes

- PR #265 contains `spec/260521-기능통합/requirements.md` and `spec/260521-기능통합/tasks.md`, so it satisfies the two-file spec gate rule.
- The file `spec/260521-기능통합/disign.md` is misspelled in that target PR, but the gate still passes because two valid required files are present.
