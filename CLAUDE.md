# Kydax Bootstrap

Home Assistant custom integration (domain `kydax_bootstrap`, GitHub repo
`aldrouin/kydax_bootstrap`) that provisions a fresh HA box for a venue:
installs the kydax components from GitHub releases, creates the sibling
config entries via their `async_step_import`, builds the locked customer
Lovelace dashboard, and runs the family's centralized 4 AM auto-update.
Siblings: kydax_sound (`C:\Workspace\kydax_sound`), kydax_light
(`C:\Workspace\kydax_light`, the family reference), kydax_test.

## Architecture rules (must match the family)

- Config in `entry.options` (`bundle` + `provisioning`); options flow uses
  `async_show_menu`; the update listener skips the reload when only
  `provisioning` changed (the state machine writes it while running).
- `coordinator.py` holds `KydaxBootstrapHub` in `entry.runtime_data`;
  dispatcher signal `signal_update(entry_id)`; unique_ids
  `f"{entry.entry_id}_<suffix>"`; one hub device.
- Provisioning is a resumable state machine persisted in options:
  `pending → install_components → restart_pending → create_entries →
  build_dashboard → (final_restart_pending) → done`, failures become
  `error:<phase>`; every step is idempotent, the Resume button retries.
- **Never couple to HACS internals** — components install from GitHub
  release zipballs/assets (`github.py` + `installer.py`); HACS
  registration is best-effort cosmetic only.
- `dashboard.py` is the only module touching Lovelace internals, fully
  guarded; a failure degrades to "create the dashboard manually".
- Translations: `strings.json` EN source, `translations/en.json` copy,
  `translations/fr.json` French mirror — same commit, always.

## Environment & verification

- No Python on this machine (Windows); Node.js for helper scripts.
- Verify in the real HA image before every release:
  ```bash
  docker run --rm -v "C:\Workspace\kydax_bootstrap\custom_components:/cc:ro" ghcr.io/home-assistant/home-assistant:stable python3 -c "import sys; sys.path.insert(0,'/cc'); import kydax_bootstrap.config_flow; print('OK')"
  ```
  Import every module; add small logic asserts.
- CI: hassfest on push.

## Release routine

Same as the family: bump `manifest.json` (semver), commit, push,
`gh release create vX.Y.Z`; the user installs via HACS custom repository.
Bootstrap updates itself afterwards (it is a component of its own bundle).
