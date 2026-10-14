# Releasing

How to cut a release of Omaudible. Users install from the repository's default branch (`omarchy plugin add` and `omarchy plugin update` take the current `main`), so a release is a version, a changelog entry and a tag on a commit that is already on `main`.

## Before you start

- `main` is green: `make test` and `make lint` pass on a clean checkout. `make lint` includes `omarchy plugin validate .`, which needs an Omarchy machine.
- The manual checks for anything user-visible in this release are recorded in `docs/MANUAL-TEST.md`.
- For a release that changes setup, sign-in or downloads, run the clean-install test (PLAN R5) first.

## Steps

1. **Pick the version.** Bump the minor version for new features and the patch version for fixes only.
2. **Set it in three places**, which must match:
   - `manifest.json` → `version` (the version Omarchy and the marketplace read; the diagnostic report quotes it)
   - `pyproject.toml` → `[project] version`
   - `backend/pyproject.toml` → `[project] version`

   `Service.qml` also has a fallback version for the diagnostic report, used only if the manifest cannot be read; keep it in step too.
3. **Update `CHANGELOG.md`.** Replace `(unreleased)` with today's date and check the entry against the merged pull requests since the last tag:

   ```sh
   git log --merges --format='%s%n  %b' v<previous>..main
   ```

   For the first release there is no earlier tag; use the whole history.

4. **Check the release locally.**

   ```sh
   make test
   make lint
   omarchy plugin validate .
   ```

5. **Merge** the version and changelog change to `main` through a pull request.
6. **Tag the merge commit** and push the tag:

   ```sh
   git switch main && git pull --ff-only
   git tag -a v<version> -m "v<version>"
   git push origin v<version>
   ```

7. **Create the GitHub release** from the tag, with the changelog entry as its notes:

   ```sh
   gh release create v<version> --title "v<version>" --notes-file <(sed -n '/^## <version>/,/^## /{/^## /!p}' CHANGELOG.md)
   ```

8. **Update an existing install** and check that it picks up the release:

   ```sh
   omarchy plugin update latentoperator.audible
   ```

   Open the drawer and play a book.

## Marketplace

The marketplace lists an exact commit. After a release that should reach marketplace users, request verification of the new commit through the marketplace's **Plugin verification** issue form. Validation, the security baseline scan and approval all refer to that exact commit SHA. See <https://plugins.omarchy.org/publish.html>.

## Pinned dependencies

`backend/requirements.lock` pins `audible-cli` and `audible`. `setup` records the digest, installed pins, interpreter compatibility and file fingerprints, and probes the environment offline before a no-op. Status offers **Set up** again for missing, broken or usable-old environments, without spawning a probe on each poll; explicit setup repairs/rebuilds as needed. A failed rebuild restores only a probed-usable previous environment, which remains dispatchable while setup is offered again. Keep new code compatible with supported fallback packages, and note any pin change in the changelog and README's "What setup installs" section.

The development `uv.lock` also records the root project version; refresh it with `uv lock --offline` after a version bump so frozen checks use consistent metadata.
