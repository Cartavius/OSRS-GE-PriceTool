# Local scripts

- `smoke-test.ps1` starts `server.py`, waits for the app to come up, and validates a few core endpoints.
- `smoke-test-docker.ps1` builds and starts the Docker container, validates core endpoints, and stops it unless `-KeepRunning` is used.
- `preview-ui.ps1` starts the app for manual browser inspection using either direct Python or Docker.
