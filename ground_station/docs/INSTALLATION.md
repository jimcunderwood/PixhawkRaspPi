# Ground Station Installation

The ground station is a web application, so "installation" means either:

- running the Vite dev server locally on Linux, macOS, or Windows
- building and serving the web UI in Docker
- wrapping the built web UI in the Electron desktop shell
- wrapping the same web build in the Capacitor mobile shell

The web UI reads the companion URL at runtime, so you can point one ground
station build at different companion hosts without rebuilding.

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

Install Node.js 20+ with your preferred method, then:

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

If `COMPANION_BASE_URL` is not set, the UI falls back to the bundled mock
state so the dashboard still opens without a live companion.

## Docker Compose

The repository root includes a `docker-compose.yml` with separate profiles for
the companion and ground station. Run the ground station on its own host with:

```bash
docker compose --profile ground-station up -d
```

Set `COMPANION_BASE_URL` in the host environment or a Compose `.env` file so
the web container can reach the companion on the other machine.

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

## Mobile Shell

The Capacitor shell reuses the same web build. After the web UI is built, run:

```bash
cd ../mobile
npm run sync:web
```

Use `CAPACITOR_SERVER_URL` when you want the mobile shell to point at a hosted
web UI during development.
