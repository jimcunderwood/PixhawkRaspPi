import { resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { app, BrowserWindow } from 'electron';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const webAppDirectory = resolve(__dirname, '../web');
const webDistDirectory = resolve(webAppDirectory, 'dist');
const defaultPort = Number(process.env.GROUND_STATION_DESKTOP_PORT || 4173);
const host = '127.0.0.1';

let serverHandle;

async function createWindow() {
  const window = new BrowserWindow({
    width: 1600,
    height: 1000,
    minWidth: 1280,
    minHeight: 800,
    backgroundColor: '#0b1018',
    autoHideMenuBar: true,
    title: 'Drone Ground Station',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  await window.loadURL(`http://${host}:${defaultPort}`);
}

async function startServer() {
  const { startGroundStationServer } = await import('../web/server.mjs');
  return startGroundStationServer({
    host,
    port: defaultPort,
    distDir: webDistDirectory,
    dataDir: process.env.GROUND_STATION_DATA_DIRECTORY || resolve(app.getPath('userData'), 'ground-station'),
    shellLabel: 'desktop',
    companionBaseUrl: process.env.COMPANION_BASE_URL?.trim(),
    sqlJsModuleUrl: pathToFileURL(resolve(__dirname, './node_modules/sql.js/dist/sql-wasm.js')).href,
  });
}

app.whenReady().then(async () => {
  serverHandle = await startServer();
  await createWindow();

  app.on('activate', async () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      await createWindow();
    }
  });
});

app.on('before-quit', () => {
  if (serverHandle) {
    void serverHandle.close();
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    if (serverHandle) {
      void serverHandle.close();
    }
    app.quit();
  }
});
