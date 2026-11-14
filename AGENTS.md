# Agent notes

Home Assistant custom integration (`custom_components/magnum_w_controller`), distributed via HACS.
Validate every change with `mise run test` and `mise run lint`. Use Conventional
Commits, matching the existing git history, with single-line commit messages. Keep
PRs simple: a short title and a brief body. Never edit `CHANGELOG.md`,
`.release-please-manifest.json` or the `version` in `manifest.json`; release-please
owns them.
