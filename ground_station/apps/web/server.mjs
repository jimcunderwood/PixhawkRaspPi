import { createServer } from 'node:http';
import { extname, resolve } from 'node:path';
import { access, mkdir, readFile, writeFile } from 'node:fs/promises';
import { constants as fsConstants } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { homedir } from 'node:os';
import crypto from 'node:crypto';

const moduleDir = fileURLToPath(new URL('.', import.meta.url));
const defaultDistDir = resolve(moduleDir, 'dist');
const defaultDataDir = process.env.GROUND_STATION_DATA_DIRECTORY || resolve(homedir(), '.ground-station');
const defaultPort = Number(process.env.GROUND_STATION_PORT || 8080);
const defaultHost = process.env.GROUND_STATION_HOST || '0.0.0.0';
const defaultShellLabel = process.env.GROUND_STATION_SHELL_LABEL || 'web';
const defaultApiKey = process.env.API_KEY?.trim() || process.env.COMPANION_API_KEY?.trim() || 'ee3ba92d63dcc1b0f54605b9351f00bf16444383e1a8d4cd7cea8825aa8b8c38';
const defaultAdminUsername = process.env.GROUND_STATION_ADMIN_USERNAME?.trim() || 'admin';

const contentTypes = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.txt': 'text/plain; charset=utf-8',
};

function jsonResponse(response, statusCode, payload, headers = {}) {
  response.writeHead(statusCode, {
    'content-type': 'application/json; charset=utf-8',
    ...headers,
  });
  response.end(JSON.stringify(payload));
}

function textResponse(response, statusCode, payload, headers = {}) {
  response.writeHead(statusCode, {
    'content-type': 'text/plain; charset=utf-8',
    ...headers,
  });
  response.end(payload);
}

function getCookie(request, name) {
  const raw = request.headers.cookie;
  if (!raw) {
    return undefined;
  }

  const match = raw
    .split(';')
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${name}=`));

  return match ? decodeURIComponent(match.slice(name.length + 1)) : undefined;
}

function setCookie(name, value, options = {}) {
  const parts = [`${name}=${encodeURIComponent(value)}`, 'Path=/', 'HttpOnly', 'SameSite=Lax'];
  if (options.maxAgeSeconds !== undefined) {
    parts.push(`Max-Age=${Math.max(0, Math.floor(options.maxAgeSeconds))}`);
  }
  if (options.secure) {
    parts.push('Secure');
  }
  return parts.join('; ');
}

function randomId(prefix) {
  return `${prefix}-${crypto.randomBytes(12).toString('hex')}`;
}

function hashPassword(password, salt) {
  return crypto.scryptSync(password, salt, 64).toString('hex');
}

function buildTelemetryEndpoint(companionEndpoint) {
  try {
    const url = new URL(companionEndpoint || 'http://192.168.1.140:8000');
    url.protocol = url.protocol === 'https:' || url.protocol === 'wss:' ? 'wss:' : 'ws:';
    url.pathname = '/ws/telemetry';
    url.search = '';
    url.hash = '';
    return url.toString();
  } catch {
    return 'ws://192.168.1.140:8000/ws/telemetry';
  }
}

function createDefaultSettings(userId, username, displayName, companionBaseUrl, apiKey = '') {
  const companionEndpoint = companionBaseUrl || 'http://192.168.1.140:8000';
  const telemetryEndpoint = buildTelemetryEndpoint(companionEndpoint);
  const transportType = companionEndpoint.startsWith('ws') || companionEndpoint.startsWith('wss') ? 'websocket' : 'http';

  return {
    user_id: userId,
    username,
    display_name: displayName,
    active_profile_id: 'profile-default',
    profiles: [
      {
        profile_id: 'profile-default',
        label: 'Primary profile',
        companion_base_url: companionBaseUrl || undefined,
        selected_drone_id: 'drone-01',
        fleet: {
          fleet_id: 'field-alpha',
          default_transport: transportType,
          drones: [
            {
              drone_id: 'drone-01',
              callsign: 'Alpha',
              role: 'leader',
              transport: {
                type: transportType,
                endpoint: companionEndpoint,
                api_key: apiKey,
                control_token: '',
              },
              endpoints: [companionEndpoint, telemetryEndpoint],
              capabilities: ['arm', 'takeoff', 'land', 'mission', 'telemetry'],
              status: 'active',
              last_heartbeat: new Date().toISOString(),
            },
            {
              drone_id: 'drone-02',
              callsign: 'Bravo',
              role: 'wing',
              transport: {
                type: 'udp',
                endpoint: 'udp://192.168.1.51:14550',
                api_key: apiKey,
                control_token: '',
              },
              endpoints: ['udp://192.168.1.51:14550'],
              capabilities: ['mission', 'telemetry'],
              status: 'staged',
              last_heartbeat: new Date().toISOString(),
            },
          ],
        },
      },
    ],
  };
}

async function loadSqlJs(sqlJsModuleUrl) {
  const sqlJsModule = await import(sqlJsModuleUrl);
  const initSqlJs = sqlJsModule.default ?? sqlJsModule;
  const distDir = new URL('.', sqlJsModuleUrl);

  return initSqlJs({
    locateFile: (file) => new URL(file, distDir).href,
  });
}

class SettingsStore {
  constructor({ dataDir, sqlJsModuleUrl, companionBaseUrl, apiKey, adminUsername }) {
    this.dataDir = dataDir;
    this.sqlJsModuleUrl = sqlJsModuleUrl;
    this.companionBaseUrl = companionBaseUrl;
    this.apiKey = apiKey;
    this.adminUsername = adminUsername;
    this.dbPath = resolve(dataDir, 'settings.sqlite3');
    this.sql = undefined;
    this.db = undefined;
  }

  async init() {
    await mkdir(this.dataDir, { recursive: true });
    this.sql = await loadSqlJs(this.sqlJsModuleUrl);
    const exists = await access(this.dbPath, fsConstants.F_OK)
      .then(() => true)
      .catch(() => false);
    if (exists) {
      const bytes = await readFile(this.dbPath);
      this.db = new this.sql.Database(bytes);
    } else {
      this.db = new this.sql.Database();
    }

    this.db.run(`
      CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT NOT NULL UNIQUE,
        display_name TEXT,
        password_hash TEXT NOT NULL,
        password_salt TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
      );

      CREATE TABLE IF NOT EXISTS settings (
        user_id TEXT PRIMARY KEY,
        payload TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
      );
    `);
    this.ensureDefaultAdminUser();
    await this.save();
  }

  async save() {
    const bytes = this.db.export();
    await writeFile(this.dbPath, Buffer.from(bytes));
  }

  nowIso() {
    return new Date().toISOString();
  }

  getUserCount() {
    const stmt = this.db.prepare('SELECT COUNT(*) AS count FROM users');
    try {
      stmt.step();
      return stmt.getAsObject().count || 0;
    } finally {
      stmt.free();
    }
  }

  getUserByUsername(username) {
    const stmt = this.db.prepare('SELECT * FROM users WHERE username = ? LIMIT 1');
    try {
      stmt.bind([username]);
      if (!stmt.step()) {
        return undefined;
      }
      return stmt.getAsObject();
    } finally {
      stmt.free();
    }
  }

  getUserById(userId) {
    const stmt = this.db.prepare('SELECT * FROM users WHERE id = ? LIMIT 1');
    try {
      stmt.bind([userId]);
      if (!stmt.step()) {
        return undefined;
      }
      return stmt.getAsObject();
    } finally {
      stmt.free();
    }
  }

  getSession(token) {
    const stmt = this.db.prepare('SELECT * FROM sessions WHERE token = ? LIMIT 1');
    try {
      stmt.bind([token]);
      if (!stmt.step()) {
        return undefined;
      }
      return stmt.getAsObject();
    } finally {
      stmt.free();
    }
  }

  getSessionUser(request) {
    const token = getCookie(request, 'gs_session');
    if (!token) {
      return undefined;
    }

    const session = this.getSession(token);
    if (!session) {
      return undefined;
    }

    if (new Date(session.expires_at).getTime() <= Date.now()) {
      this.db.run('DELETE FROM sessions WHERE token = ?', [token]);
      void this.save();
      return undefined;
    }

    return this.getUserById(session.user_id);
  }

  getSettingsForUserId(userId) {
    const stmt = this.db.prepare('SELECT payload FROM settings WHERE user_id = ? LIMIT 1');
    try {
      stmt.bind([userId]);
      if (!stmt.step()) {
        return undefined;
      }
      const row = stmt.getAsObject();
      return JSON.parse(row.payload);
    } finally {
      stmt.free();
    }
  }

  upsertSettings(userId, payload) {
    const now = this.nowIso();
    this.db.run(
      `
      INSERT INTO settings (user_id, payload, created_at, updated_at)
      VALUES (?, ?, ?, ?)
      ON CONFLICT(user_id) DO UPDATE SET
        payload = excluded.payload,
        updated_at = excluded.updated_at
      `,
      [userId, JSON.stringify(payload), now, now],
    );
  }

  defaultSettingsForUser(userRow) {
    return createDefaultSettings(
      userRow.id,
      userRow.username,
      userRow.display_name || userRow.username,
      this.companionBaseUrl,
      this.apiKey,
    );
  }

  updateUserPassword(userId, password) {
    const now = this.nowIso();
    const salt = crypto.randomBytes(16).toString('hex');
    this.db.run(
      `
      UPDATE users
      SET password_hash = ?, password_salt = ?, updated_at = ?
      WHERE id = ?
      `,
      [hashPassword(password, salt), salt, now, userId],
    );
  }

  fillMissingApiKeys(settings) {
    if (!this.apiKey) {
      return settings;
    }

    let changed = false;
    const profiles = settings.profiles.map((profile) => ({
      ...profile,
      fleet: {
        ...profile.fleet,
        drones: profile.fleet.drones.map((drone) => {
          if (drone.transport.api_key?.trim()) {
            return drone;
          }

          changed = true;
          return {
            ...drone,
            transport: {
              ...drone.transport,
              api_key: this.apiKey,
            },
          };
        }),
      },
    }));

    return changed ? { ...settings, profiles } : settings;
  }

  ensureSettingsForUser(userRow) {
    let settings = this.getSettingsForUserId(userRow.id);
    if (!settings) {
      settings = this.defaultSettingsForUser(userRow);
      this.upsertSettings(userRow.id, settings);
      void this.save();
    }
    return settings;
  }

  ensureDefaultAdminUser() {
    const adminPassword = this.apiKey || 'admin';
    let adminRow = this.getUserByUsername(this.adminUsername);
    if (!adminRow) {
      adminRow = this.createUser({
        username: this.adminUsername,
        password: adminPassword,
        displayName: 'Admin',
        seedSettings: false,
      });
    } else if (this.apiKey && !this.verifyPassword(adminRow, adminPassword)) {
      this.updateUserPassword(adminRow.id, adminPassword);
      adminRow = this.getUserById(adminRow.id);
    }
    const settings = this.ensureSettingsForUser(adminRow);
    const settingsWithApiKey = this.fillMissingApiKeys(settings);
    if (settingsWithApiKey !== settings) {
      this.upsertSettings(adminRow.id, settingsWithApiKey);
    }
  }

  createUser({ username, password, displayName, seedSettings = true }) {
    const now = this.nowIso();
    const salt = crypto.randomBytes(16).toString('hex');
    const userId = randomId('user');
    this.db.run(
      `
      INSERT INTO users (id, username, display_name, password_hash, password_salt, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
      `,
      [userId, username, displayName || username, hashPassword(password, salt), salt, now, now],
    );
    const userRow = this.getUserById(userId);
    if (seedSettings && userRow) {
      this.ensureSettingsForUser(userRow);
    }
    return userRow;
  }

  verifyPassword(userRow, password) {
    const computed = hashPassword(password, userRow.password_salt);
    return crypto.timingSafeEqual(Buffer.from(computed, 'hex'), Buffer.from(userRow.password_hash, 'hex'));
  }

  createSession(userId, leaseDays = 7) {
    const token = randomId('session');
    const createdAt = new Date();
    const expiresAt = new Date(createdAt.getTime() + leaseDays * 24 * 60 * 60 * 1000);
    this.db.run(
      `
      INSERT INTO sessions (token, user_id, created_at, expires_at)
      VALUES (?, ?, ?, ?)
      `,
      [token, userId, createdAt.toISOString(), expiresAt.toISOString()],
    );
    return { token, expiresAt };
  }

  deleteSession(token) {
    this.db.run('DELETE FROM sessions WHERE token = ?', [token]);
  }

  buildSessionState(userRow) {
    const settings = this.ensureSettingsForUser(userRow);
    return {
      authenticated: true,
      has_users: this.getUserCount() > 0,
      user: {
        user_id: userRow.id,
        username: userRow.username,
        display_name: userRow.display_name || userRow.username,
      },
      settings,
    };
  }

  createAccount({ username, password, displayName }) {
    const existing = this.getUserByUsername(username);
    if (existing) {
      return undefined;
    }

    const userRow = this.createUser({ username, password, displayName });
    void this.save();
    return {
      authenticated: false,
      has_users: this.getUserCount() > 0,
      created: true,
      created_username: userRow.username,
    };
  }

  login({ username, password }) {
    const userRow = this.getUserByUsername(username);
    if (!userRow || !this.verifyPassword(userRow, password)) {
      return undefined;
    }

    const session = this.createSession(userRow.id);
    void this.save();
    return {
      token: session.token,
      expiresAt: session.expiresAt,
      state: this.buildSessionState(userRow),
    };
  }
}

async function readJsonBody(request) {
  return new Promise((resolveBody, rejectBody) => {
    const chunks = [];
    request.on('data', (chunk) => chunks.push(chunk));
    request.on('end', () => {
      try {
        const raw = Buffer.concat(chunks).toString('utf-8');
        resolveBody(raw ? JSON.parse(raw) : {});
      } catch (error) {
        rejectBody(error);
      }
    });
    request.on('error', rejectBody);
  });
}

function createStaticHandler({ distDir, shellLabel, companionBaseUrl }) {
  return async function handleStatic(request, response, pathname) {
    const safePath = pathname === '/' ? '/index.html' : pathname;
    const filePath = resolve(distDir, `.${safePath}`);
    const root = resolve(distDir);
    if (!filePath.startsWith(root)) {
      textResponse(response, 403, 'Forbidden');
      return;
    }

    if (safePath === '/runtime-config.json') {
      jsonResponse(response, 200, {
        companionBaseUrl: companionBaseUrl?.trim() || undefined,
        shellLabel,
      });
      return;
    }

    try {
      const stat = await access(filePath, fsConstants.F_OK).then(() => true).catch(() => false);
      if (!stat) {
        if (safePath === '/index.html') {
          textResponse(response, 404, 'Build the web app first: npm --prefix ../web run build');
          return;
        }
        await handleStatic(request, response, '/index.html');
        return;
      }

      const extension = extname(filePath).toLowerCase();
      const contentType = contentTypes[extension] || 'application/octet-stream';
      const body = await readFile(filePath);
      response.writeHead(200, { 'content-type': contentType });
      response.end(body);
    } catch {
      if (safePath === '/index.html') {
        textResponse(response, 404, 'Build the web app first: npm --prefix ../web run build');
        return;
      }
      await handleStatic(request, response, '/index.html');
    }
  };
}

export async function startGroundStationServer({
  host = defaultHost,
  port = defaultPort,
  distDir = defaultDistDir,
  dataDir = defaultDataDir,
  shellLabel = defaultShellLabel,
  companionBaseUrl = process.env.COMPANION_BASE_URL?.trim(),
  apiKey = defaultApiKey,
  adminUsername = defaultAdminUsername,
  sqlJsModuleUrl = pathToFileURL(resolve(moduleDir, 'node_modules/sql.js/dist/sql-wasm.js')).href,
} = {}) {
  const store = new SettingsStore({
    dataDir,
    sqlJsModuleUrl,
    companionBaseUrl,
    apiKey,
    adminUsername,
  });
  await store.init();

  const handleStatic = createStaticHandler({ distDir, shellLabel, companionBaseUrl });

  const server = createServer(async (request, response) => {
    const url = new URL(request.url || '/', `http://${host}:${port}`);

    if (url.pathname === '/api/settings/session') {
      if (request.method === 'GET') {
        const userRow = store.getSessionUser(request);
        if (!userRow) {
          jsonResponse(response, 200, {
            authenticated: false,
            has_users: store.getUserCount() > 0,
          });
          return;
        }

        jsonResponse(response, 200, store.buildSessionState(userRow));
        return;
      }

      if (request.method === 'POST') {
        const body = await readJsonBody(request).catch(() => undefined);
        if (!body || typeof body.username !== 'string' || typeof body.password !== 'string') {
          jsonResponse(response, 400, { message: 'username and password are required' });
          return;
        }
        const username = body.username.trim();
        if (!username || !body.password) {
          jsonResponse(response, 400, { message: 'username and password are required' });
          return;
        }

        if (Boolean(body.create)) {
          const createdState = store.createAccount({
            username,
            password: body.password,
            displayName: typeof body.display_name === 'string' ? body.display_name.trim() : undefined,
          });

          if (!createdState) {
            jsonResponse(response, 409, { message: 'username already exists' });
            return;
          }

          response.setHeader(
            'set-cookie',
            setCookie('gs_session', '', {
              maxAgeSeconds: 0,
              secure: request.headers['x-forwarded-proto'] === 'https' || request.socket.encrypted,
            }),
          );
          jsonResponse(response, 201, createdState);
          return;
        }

        const loginResult = store.login({
          username,
          password: body.password,
        });

        if (!loginResult) {
          jsonResponse(response, 401, { message: 'invalid credentials' });
          return;
        }

        response.setHeader(
          'set-cookie',
          setCookie('gs_session', loginResult.token, {
            maxAgeSeconds: 7 * 24 * 60 * 60,
            secure: request.headers['x-forwarded-proto'] === 'https' || request.socket.encrypted,
          }),
        );
        jsonResponse(response, 200, loginResult.state);
        return;
      }

      if (request.method === 'DELETE') {
        const token = getCookie(request, 'gs_session');
        if (token) {
          store.deleteSession(token);
          await store.save();
        }
        response.setHeader(
          'set-cookie',
          setCookie('gs_session', '', {
            maxAgeSeconds: 0,
            secure: request.headers['x-forwarded-proto'] === 'https' || request.socket.encrypted,
          }),
        );
        jsonResponse(response, 200, { authenticated: false, has_users: store.getUserCount() > 0 });
        return;
      }
    }

    if (url.pathname === '/api/settings/profile') {
      if (request.method === 'GET') {
        const userRow = store.getSessionUser(request);
        if (!userRow) {
          jsonResponse(response, 401, { message: 'not authenticated' });
          return;
        }

        const settings = store.getSettingsForUserId(userRow.id);
        if (!settings) {
          jsonResponse(response, 404, { message: 'no settings found' });
          return;
        }

        jsonResponse(response, 200, { data: settings });
        return;
      }

      if (request.method === 'PUT') {
        const userRow = store.getSessionUser(request);
        if (!userRow) {
          jsonResponse(response, 401, { message: 'not authenticated' });
          return;
        }

        const body = await readJsonBody(request).catch(() => undefined);
        if (!body || typeof body.user_id !== 'string' || !Array.isArray(body.profiles)) {
          jsonResponse(response, 400, { message: 'invalid settings payload' });
          return;
        }

        if (body.user_id !== userRow.id) {
          jsonResponse(response, 403, { message: 'settings belong to a different user' });
          return;
        }

        store.upsertSettings(userRow.id, body);
        await store.save();
        jsonResponse(response, 200, { data: body });
        return;
      }
    }

    if (url.pathname === '/health') {
      jsonResponse(response, 200, {
        status: 'ok',
        data: {
          status: 'ok',
          shellLabel,
          data_directory: dataDir,
          configured_companion_base_url: companionBaseUrl || null,
        },
      });
      return;
    }

    await handleStatic(request, response, url.pathname);
  });

  await new Promise((resolveServer, rejectServer) => {
    server.on('error', rejectServer);
    server.listen(port, host, resolveServer);
  });

  return {
    server,
    port,
    host,
    close: () => new Promise((resolveClose) => server.close(() => resolveClose())),
  };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  startGroundStationServer().then(({ host, port }) => {
    console.log(`Ground station running at http://${host}:${port}`);
  }).catch((error) => {
    console.error(error);
    process.exit(1);
  });
}
