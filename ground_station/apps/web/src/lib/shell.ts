export type ShellKind = 'web' | 'desktop' | 'mobile' | 'unknown';

export type ShellContext = {
  kind: ShellKind;
  label: string;
  detail: string;
};

function hasElectron(): boolean {
  const w = globalThis as typeof globalThis & { process?: { versions?: { electron?: string } } };
  return Boolean(w.process?.versions?.electron);
}

function hasCapacitor(): boolean {
  const w = globalThis as typeof globalThis & { Capacitor?: { getPlatform?: () => string } };
  return Boolean(w.Capacitor?.getPlatform?.());
}

export function detectShellContext(): ShellContext {
  if (hasElectron()) {
    return { kind: 'desktop', label: 'Desktop', detail: 'Electron shell' };
  }

  if (hasCapacitor()) {
    return { kind: 'mobile', label: 'Mobile', detail: 'Capacitor shell' };
  }

  return { kind: 'web', label: 'Web', detail: 'Browser shell' };
}
