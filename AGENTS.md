# Office Workbench source repository

This directory contains distributable source, never private office data.
Read README.md and docs/architecture.md before changing code.
Use only synthetic inputs generated in temporary directories outside this checkout.
Never initialize a private workspace inside a Git checkout, import user data, or copy global agent settings.
Run `python -I -B tests/run.py` and `python -I -B tools/release.py check` before delivery.
Do not publish, add a remote, or adopt a license on the owner's behalf without authorization.
The installed behavior is in templates/AGENTS.md; this file governs source maintenance only.
