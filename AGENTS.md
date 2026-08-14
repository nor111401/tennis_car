# Repository maintenance rules

Before changing this repository, read `PROJECT_STATE.md` completely. It is the project's durable
technical handoff and source of truth.

After changing source code, model artifacts, configuration defaults, protocols, deployment behavior,
hardware assumptions, tests, or user-facing control behavior:

1. Update the `Last updated` date and relevant sections in `PROJECT_STATE.md`.
2. Add a concise entry to its change log.
3. Record the exact tests that passed and any tests that could not run.
4. Keep safety invariants and known limitations accurate.
5. Never store passwords, private keys, access tokens, Wi-Fi credentials, or temporary authentication
   helpers in the repository or in `PROJECT_STATE.md`.

Do not delete `training_data/`, model files, vehicle protocol documents, or Raspberry Pi boot/UART
backups unless the user explicitly names those targets. Generated caches, logs, screenshots, local
virtual environments, build output, and credential helpers are disposable.
