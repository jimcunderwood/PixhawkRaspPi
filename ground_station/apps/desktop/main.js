import { createServer } from 'node:http';
import { extname, resolve } from 'node:path';
import { readFile, stat } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { app, BrowserWindow } from 'electron';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const webDistDirectory = resolve(__dirname, '../web/dist');
const host = '127.0.0.1';
const port = Number(process.env.GROUND_STATION_DESKTOP_PORT || 4173);

const contentTypes = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.txt': 'text/plain; charset=utf-8',
};

function runtimeConfigPayload() {
  return JSON.stringify(
    {
      companionBaseUrl: process.env.COMPANION_BASE_URL?.trim() || undefined,
      shellLabel: 'desktop',
    },
    null,
    2,
  );
}

async function serveFile(response, pathname) {
  const safePath = pathname === '/' ? '/index.html' : pathname;
  const filePath = resolve(webDistDirectory, `.${safePath}`);
  const webRoot = resolve(webDistDirectory);
  if (!filePath.startsWith(webRoot)) {
    response.writeHead(403);
    response.end('Forbidden');
    return;
  }

  if (safePath === '/runtime-config.json') {
    response.writeHead(200, { 'content-type': contentTypes['.json'] });
    response.end(runtimeConfigPayload());
    return;
  }

  try {
    const fileStat = await stat(filePath);
    if (fileStat.isDirectory()) {
      await serveFile(response, '/index.html');
      return;
    }

    const extension = extname(filePath).toLowerCase();
    const contentType = contentTypes[extension] || 'application/octet-stream';
    response.writeHead(200, { 'content-type': contentType });
    response.end(await readFile(filePath));
  } catch {
    if (safePath === '/index.html') {
      response.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' });
      response.end('Build the web app first: npm --prefix ../web run build');
      return;
    }
    await serveFile(response, '/index.html');
  }
}

async function startStaticServer() {
  return new Promise((resolveServer, rejectServer) => {
    const server = createServer((request, response) => {
      const url = new URL(request.url || '/', `http://${host}:${port}`);
      void serveFile(response, url.pathname);
    });

    server.on('error', rejectServer);
    server.listen(port, host, () => resolveServer(server));
  });
}

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

  await window.loadURL(`http://${host}:${port}`);
}

let server;

app.whenReady().then(async () => {
  server = await startStaticServer();
  await createWindow();

  app.on('activate', async () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      await createWindow();
    }
  });
});

app.on('before-quit', () => {
  if (server) {
    server.close();
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    if (server) {
      server.close();
    }
    app.quit();
  }
});
