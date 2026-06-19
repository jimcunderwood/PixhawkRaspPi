import type { CapacitorConfig } from '@capacitor/cli';

const runtimeUrl = process.env.CAPACITOR_SERVER_URL?.trim();

const config: CapacitorConfig = {
  appId: 'com.pixhawk.groundstation',
  appName: 'Ground Station',
  webDir: '../web/dist',
  bundledWebRuntime: false,
  server: runtimeUrl
    ? {
        url: runtimeUrl,
        cleartext: runtimeUrl.startsWith('http://'),
      }
    : undefined,
  android: {
    allowMixedContent: true,
  },
};

export default config;
