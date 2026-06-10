# Release checklist

Use this checklist when cutting a Burnguard release from `main`.

## v0.1.0 release candidate

1. Confirm the package version in `pyproject.toml` matches the intended tag.
2. Confirm `CHANGELOG.md` has a dated entry for the release.
3. Confirm `SECURITY.md` names the supported release line and still calls out prototype limitations.
4. Run the test suite on the supported Python versions in CI.
5. Run a local smoke test:
   - create a virtual environment
   - install `pip install -e ".[dev]"`
   - run `python -m token_governor seed-demo`
   - run `uvicorn token_governor.main:app --reload`
   - open `/`, `/keys`, `/sessions`, `/requests`, and `/healthz`
   - send one non-streaming Chat Completions request
   - send one streaming Chat Completions request
   - confirm both requests are metered on `/requests`
6. Review the README quickstart, agent integration guide, and demo GIF for stale claims.
7. Create and push the annotated tag:

   ```bash
   git checkout main
   git pull --ff-only
   git tag -a v0.1.0 -m "Burnguard v0.1.0"
   git push origin v0.1.0
   ```

8. Create a GitHub release from the tag using the `CHANGELOG.md` entry as the release notes.
9. After the release is live, publish the soft-launch posts in `docs/launch-posts.md`.

## Post-release checks

- Verify the GitHub release page links to the correct tag.
- Verify the README test badge is green on `main`.
- Verify SECURITY.md still reflects the supported line after any patch releases.
- Watch early issues for installation friction, pricing drift reports, and agent-specific integration gaps.
