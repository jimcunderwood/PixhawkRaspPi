# Ground Station Installation

Invariant:

- Companion and Ground Station are separate installs and separate runtime targets.
- Ground Station depends on at least one Companion being available.
- Any install, config, docs, or code changes for Ground Station assume the Companion exists on another machine or service, not bundled inside it.

The ground station is a web application, so "installation" means either:

- running the Vite dev server locally on Linux, macOS, or Windows
- building and serving the web UI in Docker
- wrapping the built web UI in the Electron desktop shell
- wrapping the same web build in the Capacitor mobile shell

The web UI reads the companion URL at runtime, so you can point one ground
station build at a reachable Companion on another machine or service without
rebuilding. When the app is served by the built-in Node server, it also
exposes a SQLite-backed login and settings API so each user can keep separate
runtime profiles and per-drone connection endpoints.

## Prerequisites

- Node.js 20 or newer
- npm 10 or newer
- Git
- A modern browser

## Clone The Repository

```bash
git clone <repository-url>
cd PixhawkRaspPi/ground_station/apps/web
npm install
```

## Linux

### Native install

On Debian or Ubuntu:

```bash
sudo apt update
sudo apt install -y git curl
```

Install Node.js 20+ with your preferred method, then point the UI at a
reachable Companion:

```bash
cd PixhawkRaspPi/ground_station/apps/web
npm install
export COMPANION_BASE_URL=http://192.168.1.50:8000
npm run dev -- --host 0.0.0.0
```

Open the printed local URL in your browser.

### Docker

Build the image from the repository root:

```bash
docker build -f ground_station/apps/web/Dockerfile -t ground-station-web .
```

Run it with a runtime env file:

```bash
cp ground_station/apps/web/.env.example ground_station/apps/web/.env
docker run --rm -p 8080:80 --env-file ground_station/apps/web/.env ground-station-web
```

Before first startup, set `COMPANION_BASE_URL` in `ground_station/apps/web/.env`
to the companion machine and copy the companion `API_KEY` into the same file.
The first startup creates the default `admin` user, uses that API key as the
admin password, and copies it into the default admin drone connection settings.

## macOS

### Native install

Install Homebrew if needed, then:

```bash
brew install git node
cd PixhawkRaspPi/ground_station/apps/web
npm install
export COMPANION_BASE_URL=http://192.168.1.50:8000
npm run dev -- --host 0.0.0.0
```

### Docker

Use the same `docker build` and `docker run` commands as Linux.

## Windows

### Native install

Install Git and Node.js 20+ with Winget or the Node.js installer, then open a
PowerShell window:

```powershell
cd C:\path\to\PixhawkRaspPi\ground_station\apps\web
npm install
$env:COMPANION_BASE_URL = "http://192.168.1.50:8000"
npm run dev -- --host 0.0.0.0
```

If you prefer `cmd.exe`:

```cmd
set COMPANION_BASE_URL=http://192.168.1.50:8000
npm run dev -- --host 0.0.0.0
```

### Docker Desktop

Use the same `docker build` and `docker run` commands as Linux. Docker Desktop
works well if you want a stable browser-facing container instead of a local
Node.js install.

## Runtime Configuration

`COMPANION_BASE_URL` controls which companion host the UI talks to:

- `http://localhost:8000` for a local companion
- `http://192.168.1.50:8000` for a Pi on the LAN
- `http://10.0.0.12:8000` for a remote field network

If `COMPANION_BASE_URL` is not set, the UI can still render the bundled mock
state for local development, but that is not the supported operator runtime.

Use full URLs in both runtime configuration and per-drone settings:

| Setting | Example URL | Where It Goes |
| --- | --- | --- |
| Companion REST/API base | `http://192.168.1.50:8000` | `COMPANION_BASE_URL` and the drone `Companion endpoint` field |
| Local companion REST/API base | `http://localhost:8000` | Only when a separate Companion install is listening on the same machine |
| Telemetry WebSocket | `ws://192.168.1.50:8000/ws/telemetry` | Drone alternate endpoints when you want an explicit telemetry URL |
| Events WebSocket | `ws://192.168.1.50:8000/ws/events` | Drone alternate endpoints or future event tooling |
| Secure companion REST/API base | `https://companion.example.com` | Use when the companion is behind HTTPS/TLS |
| Secure telemetry WebSocket | `wss://companion.example.com/ws/telemetry` | Secure WebSocket form for HTTPS/TLS deployments |
| MAVLink UDP bridge | `udp://192.168.1.51:14550` | Drone endpoint for UDP bridge connections |

Always include the protocol prefix, such as `http://`, `ws://`, `https://`,
`wss://`, or `udp://`. Put the companion API key in the `API_KEY` environment
variable and the user profile `Api Key` field; do not append it manually to
these URLs.

## Docker Compose

The repository root includes a `docker-compose.yml` with separate profiles for
the companion and ground station. Run the ground station on its own host with:

```bash
docker compose --profile ground-station up -d
```

For a separate-machine install, copy `ground_station/apps/web/.env.example` to
`ground_station/apps/web/.env` on the ground-station machine. Set
`COMPANION_BASE_URL` to the companion machine and copy the companion `API_KEY`
into that file. The Compose ground-station profile reads it and uses the API key
as the default `admin` password and default drone API key.

## Desktop

The desktop shell reuses the built web app and launches it inside Electron.
After installing Node.js 20+ and npm, run:

```bash
cd PixhawkRaspPi/ground_station/apps/web
npm install
npm run build

cd ../desktop
npm install
npm run dev
```

Set `COMPANION_BASE_URL` before launching if you want the desktop shell to talk
to a live companion instance.

The desktop shell stores the same per-user settings in the Electron user-data
directory by default, so multiple operators on the same machine can keep
separate profiles.

## Mobile Shell

The Capacitor shell reuses the same web build. After the web UI is built, run:

```bash
cd ../mobile
npm run sync:web
```

Use `CAPACITOR_SERVER_URL` when you want the mobile shell to point at a hosted
web UI during development.
