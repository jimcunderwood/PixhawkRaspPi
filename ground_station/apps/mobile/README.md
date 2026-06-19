# Ground Station Mobile

Capacitor wrapper for the existing ground station web app.

This shell can be built from macOS, Windows, or Linux for Android targets.
iOS builds require macOS.

## Local build

1. Build the web app from `../web`.
2. Run `npx cap sync` in this directory.
3. Open the generated native project for iOS or Android.

## Runtime URL

Set `CAPACITOR_SERVER_URL` to point the mobile shell at a hosted ground-station web UI during development or deployment.

Example:

```bash
CAPACITOR_SERVER_URL=http://192.168.1.20:4173
```

If you want the mobile shell to use the same runtime companion URL as the web
app, set `COMPANION_BASE_URL` in the hosted web UI environment before building
the mobile bundle.

The mobile shell should reuse the same shared mission, calibration, farm, and
flight-log panels as the web and desktop shells so operators get the same
workflow coverage on a tablet or phone.
