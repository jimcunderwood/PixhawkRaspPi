import { useEffect, useMemo, useState } from 'react';
import exampleSwarmConfig from '../../../../shared/types/swarm-config.example.json';
import type {
  SwarmConfig,
  SwarmCoordinationStatus,
  SwarmPeerConfig,
  SwarmPeerTrust,
  SwarmRole,
  SwarmTransportKind,
} from '../../../../shared/types/swarm';
import { loadSwarmConfig, saveSwarmConfig } from '../../../../shared/api/swarm';
import { StatusChip } from '../../../../packages/ui/src';

type SwarmConfigEditorProps = {
  companionBaseUrl?: string;
  apiKey?: string;
  ensureControlToken: (reason: string) => Promise<string>;
  coordination?: SwarmCoordinationStatus;
};

function cloneConfig(config: SwarmConfig): SwarmConfig {
  return JSON.parse(JSON.stringify(config)) as SwarmConfig;
}

function makeDefaultConfig(): SwarmConfig {
  return cloneConfig(exampleSwarmConfig as SwarmConfig);
}

function formatAge(timestamp?: number) {
  if (!timestamp) {
    return '--';
  }

  const ageSeconds = Math.max(0, (Date.now() / 1000) - timestamp);
  if (ageSeconds < 60) {
    return `${Math.round(ageSeconds)}s ago`;
  }
  if (ageSeconds < 3600) {
    return `${Math.round(ageSeconds / 60)}m ago`;
  }
  return `${Math.round(ageSeconds / 3600)}h ago`;
}

function emptyPeer(index: number): SwarmPeerConfig {
  return {
    drone_id: `drone-${String(index + 1).padStart(2, '0')}`,
    callsign: index === 0 ? 'Companion' : `Peer ${index + 1}`,
    role: index === 0 ? 'leader' : 'follower',
    transport: {
      type: index === 0 ? 'websocket' : 'udp',
      endpoint: index === 0 ? 'ws://192.168.1.50:9001' : `udp://192.168.1.${51 + index}:14550`,
    },
    trust: index === 0 ? 'primary' : 'trusted',
    max_age_seconds: 2,
    requires_rtk: index === 0,
  };
}

function updatePeer(peers: SwarmPeerConfig[], index: number, updater: (peer: SwarmPeerConfig) => SwarmPeerConfig) {
  return peers.map((peer, peerIndex) => (peerIndex === index ? updater(peer) : peer));
}

export function SwarmConfigEditor({
  companionBaseUrl,
  apiKey,
  ensureControlToken,
  coordination,
}: SwarmConfigEditorProps) {
  const [config, setConfig] = useState<SwarmConfig>(makeDefaultConfig());
  const [message, setMessage] = useState('Loading swarm configuration...');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const loaded = await loadSwarmConfig(companionBaseUrl, apiKey);
      if (cancelled) {
        return;
      }

      setConfig(cloneConfig((loaded ?? makeDefaultConfig()) as SwarmConfig));
      setMessage(loaded ? 'Swarm config loaded' : 'Using example swarm config');
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [apiKey, companionBaseUrl]);

  const peerSummary = useMemo(
    () => config.peers.map((peer) => `${peer.callsign ?? peer.drone_id} (${peer.role})`).join(', '),
    [config.peers],
  );
  const coordinationPreview = coordination?.collision_avoidance as
    | {
        enabled?: boolean;
        nearest_peer?: {
          drone_id?: string;
          horizontal_m?: number;
          vertical_m?: number;
          updated_at?: number;
        } | null;
        active_alerts?: Array<{ drone_id_a?: string; drone_id_b?: string; severity?: 'info' | 'warning' | 'critical' }>;
        recommended_action?: string;
      }
    | undefined;
  const fusionPreview = coordination?.fusion as
    | {
        confidence?: number;
        reference_node_id?: string;
      }
    | undefined;

  async function saveConfig() {
    try {
      setSaving(true);
      setMessage('Saving swarm config...');
      const token = await ensureControlToken('Swarm config');
      if (!token) {
        setMessage('Swarm config save requires control authority');
        return;
      }

      const saved = await saveSwarmConfig(config, companionBaseUrl, apiKey, token);
      if (!saved) {
        throw new Error('swarm save failed');
      }

      setConfig(cloneConfig(saved));
      setMessage(`Saved ${saved.swarm_id ?? 'swarm'} with ${saved.peers?.length ?? 0} peers`);
    } catch (error) {
      setMessage(`Save failed: ${error instanceof Error ? error.message : 'unknown error'}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="summary-card">
      <div className="panel-head">
        <div>
          <span className="panel-label">Swarm coordination</span>
          <h3>Leader-follower editor and partitioning</h3>
        </div>
        <StatusChip
          label="Formation"
          value={coordination?.formation_mode ?? config.fusion.mode}
          tone={coordination?.formation_mode ? 'good' : 'warn'}
        />
      </div>

      <div className="stack">
        <p className="hint">{message}</p>
        <div className="config-grid">
          <label className="field">
            <span>Swarm ID</span>
            <input
              value={config.swarm_id}
              onChange={(event) => setConfig((current) => ({ ...current, swarm_id: event.target.value }))}
            />
          </label>
          <label className="field">
            <span>Self drone</span>
            <input
              value={config.self_drone_id}
              onChange={(event) => setConfig((current) => ({ ...current, self_drone_id: event.target.value }))}
            />
          </label>
          <label className="field">
            <span>Role</span>
            <select
              value={config.role}
              onChange={(event) => setConfig((current) => ({ ...current, role: event.target.value as SwarmRole }))}
            >
              {['leader', 'follower', 'relay', 'observer', 'anchor'].map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Transport</span>
            <select
              value={config.transport.type}
              onChange={(event) =>
                setConfig((current) => ({
                  ...current,
                  transport: { ...current.transport, type: event.target.value as SwarmTransportKind },
                }))
              }
            >
              {['websocket', 'udp', 'mavlink', 'http', 'ipc', 'ble', 'native'].map((kind) => (
                <option key={kind} value={kind}>
                  {kind}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Transport endpoint</span>
            <input
              value={config.transport.endpoint}
              onChange={(event) =>
                setConfig((current) => ({
                  ...current,
                  transport: { ...current.transport, endpoint: event.target.value },
                }))
              }
            />
          </label>
          <label className="field">
            <span>Fusion mode</span>
            <select
              value={config.fusion.mode}
              onChange={(event) =>
                setConfig((current) => ({
                  ...current,
                  fusion: { ...current.fusion, mode: event.target.value as SwarmConfig['fusion']['mode'] },
                }))
              }
            >
              {['none', 'separation_only', 'weighted_gnss', 'relative_pose'].map((mode) => (
                <option key={mode} value={mode}>
                  {mode}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="config-grid">
          <label className="field">
            <span>Min peers</span>
            <input
              type="number"
              min={0}
              value={config.fusion.min_peer_count}
              onChange={(event) =>
                setConfig((current) => ({
                  ...current,
                  fusion: { ...current.fusion, min_peer_count: Number(event.target.value) },
                }))
              }
            />
          </label>
          <label className="field">
            <span>Peer age limit</span>
            <input
              type="number"
              min={0.1}
              step={0.1}
              value={config.fusion.max_peer_age_seconds}
              onChange={(event) =>
                setConfig((current) => ({
                  ...current,
                  fusion: { ...current.fusion, max_peer_age_seconds: Number(event.target.value) },
                }))
              }
            />
          </label>
          <label className="field">
            <span>Reference node</span>
            <input
              value={config.fusion.reference_node_id ?? ''}
              onChange={(event) =>
                setConfig((current) => ({
                  ...current,
                  fusion: {
                    ...current.fusion,
                    reference_node_id: event.target.value,
                    require_reference_node: Boolean(event.target.value),
                  },
                }))
              }
            />
          </label>
          <label className="field">
            <span>Broadcast rate</span>
            <input
              type="number"
              min={0.1}
              step={0.1}
              value={config.broadcast.rate_hz}
              onChange={(event) =>
                setConfig((current) => ({
                  ...current,
                  broadcast: { ...current.broadcast, rate_hz: Number(event.target.value) },
                }))
              }
            />
          </label>
        </div>

        <div className="pill-row">
          <button
            type="button"
            className="ghost-button"
            onClick={() => setConfig((current) => ({ ...current, enabled: !current.enabled }))}
          >
            {config.enabled ? 'Disable swarm' : 'Enable swarm'}
          </button>
          <span className="pill">
            {coordination?.leader_drone_id ? `leader ${coordination.leader_drone_id}` : 'leader not assigned'}
          </span>
          <span className="pill">
            {coordinationPreview?.recommended_action
              ? `avoidance ${coordinationPreview.recommended_action}`
              : 'no collision action'}
          </span>
          <span className="pill">{peerSummary || 'no peers configured'}</span>
        </div>

        <div className="list-card">
          <div className="list-row">
            <div>
              <strong>Partitioning preview</strong>
              <span>{coordination?.assignments?.length ? `${coordination.assignments.length} assignments` : 'No live assignments yet'}</span>
            </div>
            <span>{fusionPreview?.confidence !== undefined ? `${Math.round(fusionPreview.confidence * 100)}% confidence` : 'preview only'}</span>
          </div>
          {(coordination?.assignments ?? []).slice(0, 4).map((assignment) => (
            <div className="list-row" key={assignment.drone_id ?? assignment.callsign ?? String(assignment.sector_index ?? 0)}>
              <div>
                <strong>{assignment.callsign ?? assignment.drone_id ?? 'drone'}</strong>
                <span>{`sector ${assignment.sector_index ?? 0} of ${assignment.sector_count ?? config.peers.length}`}</span>
              </div>
              <span>{assignment.role ?? 'member'}</span>
            </div>
          ))}
        </div>

        <div className="list-card">
          {config.peers.map((peer, index) => (
            <div className="list-row" key={`${peer.drone_id}-${index}`}>
              <div className="stack" style={{ width: '100%', gap: '0.5rem' }}>
                <div className="config-grid">
                  <label className="field">
                    <span>Drone ID</span>
                    <input
                      value={peer.drone_id}
                      onChange={(event) =>
                        setConfig((current) => ({
                          ...current,
                          peers: updatePeer(current.peers, index, (currentPeer) => ({
                            ...currentPeer,
                            drone_id: event.target.value,
                          })),
                        }))
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Callsign</span>
                    <input
                      value={peer.callsign ?? ''}
                      onChange={(event) =>
                        setConfig((current) => ({
                          ...current,
                          peers: updatePeer(current.peers, index, (currentPeer) => ({
                            ...currentPeer,
                            callsign: event.target.value,
                          })),
                        }))
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Role</span>
                    <select
                      value={peer.role}
                      onChange={(event) =>
                        setConfig((current) => ({
                          ...current,
                          peers: updatePeer(current.peers, index, (currentPeer) => ({
                            ...currentPeer,
                            role: event.target.value as SwarmRole,
                          })),
                        }))
                      }
                    >
                      {['leader', 'follower', 'relay', 'observer', 'anchor'].map((role) => (
                        <option key={role} value={role}>
                          {role}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span>Trust</span>
                    <select
                      value={peer.trust ?? 'trusted'}
                      onChange={(event) =>
                        setConfig((current) => ({
                          ...current,
                          peers: updatePeer(current.peers, index, (currentPeer) => ({
                            ...currentPeer,
                            trust: event.target.value as SwarmPeerTrust,
                          })),
                        }))
                      }
                    >
                      {['primary', 'trusted', 'normal', 'degraded'].map((trust) => (
                        <option key={trust} value={trust}>
                          {trust}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span>Transport type</span>
                    <select
                      value={peer.transport.type}
                      onChange={(event) =>
                        setConfig((current) => ({
                          ...current,
                          peers: updatePeer(current.peers, index, (currentPeer) => ({
                            ...currentPeer,
                            transport: { ...currentPeer.transport, type: event.target.value as SwarmTransportKind },
                          })),
                        }))
                      }
                    >
                      {['websocket', 'udp', 'mavlink', 'http', 'ipc', 'ble', 'native'].map((kind) => (
                        <option key={kind} value={kind}>
                          {kind}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span>Transport endpoint</span>
                    <input
                      value={peer.transport.endpoint}
                      onChange={(event) =>
                        setConfig((current) => ({
                          ...current,
                          peers: updatePeer(current.peers, index, (currentPeer) => ({
                            ...currentPeer,
                            transport: { ...currentPeer.transport, endpoint: event.target.value },
                          })),
                        }))
                      }
                    />
                  </label>
                  <label className="field">
                    <span>RTK required</span>
                    <select
                      value={peer.requires_rtk ? 'true' : 'false'}
                      onChange={(event) =>
                        setConfig((current) => ({
                          ...current,
                          peers: updatePeer(current.peers, index, (currentPeer) => ({
                            ...currentPeer,
                            requires_rtk: event.target.value === 'true',
                          })),
                        }))
                      }
                    >
                      <option value="true">true</option>
                      <option value="false">false</option>
                    </select>
                  </label>
                </div>
                <div className="config-grid">
                  <label className="field">
                    <span>Max age</span>
                    <input
                      type="number"
                      min={0.1}
                      step={0.1}
                      value={peer.max_age_seconds ?? ''}
                      onChange={(event) =>
                        setConfig((current) => ({
                          ...current,
                          peers: updatePeer(current.peers, index, (currentPeer) => ({
                            ...currentPeer,
                            max_age_seconds: Number(event.target.value),
                          })),
                        }))
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Horizontal error</span>
                    <input
                      type="number"
                      min={0.1}
                      step={0.1}
                      value={peer.max_horizontal_error_m ?? ''}
                      onChange={(event) =>
                        setConfig((current) => ({
                          ...current,
                          peers: updatePeer(current.peers, index, (currentPeer) => ({
                            ...currentPeer,
                            max_horizontal_error_m: Number(event.target.value),
                          })),
                        }))
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Vertical error</span>
                    <input
                      type="number"
                      min={0.1}
                      step={0.1}
                      value={peer.max_vertical_error_m ?? ''}
                      onChange={(event) =>
                        setConfig((current) => ({
                          ...current,
                          peers: updatePeer(current.peers, index, (currentPeer) => ({
                            ...currentPeer,
                            max_vertical_error_m: Number(event.target.value),
                          })),
                        }))
                      }
                    />
                  </label>
                  <div className="editor-actions">
                    <button
                      type="button"
                      className="ghost-button"
                      onClick={() =>
                        setConfig((current) => ({
                          ...current,
                          peers: current.peers.length > 1 ? current.peers.filter((_, peerIndex) => peerIndex !== index) : [emptyPeer(0)],
                        }))
                      }
                    >
                      Remove peer
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="editor-actions">
          <button
            type="button"
            className="ghost-button"
            onClick={() =>
              setConfig((current) => ({ ...current, peers: [...current.peers, emptyPeer(current.peers.length)] }))
            }
          >
            Add peer
          </button>
          <button type="button" className="secondary-button" onClick={() => setConfig(makeDefaultConfig())}>
            Reset to example
          </button>
          <button type="button" className="secondary-button" onClick={saveConfig} disabled={saving}>
            {saving ? 'Saving...' : 'Save swarm config'}
          </button>
        </div>
        <p className="hint">
          Operator preview: {coordinationPreview?.recommended_action ?? 'continue'}
          {coordinationPreview?.nearest_peer?.drone_id ? ` near ${coordinationPreview.nearest_peer.drone_id}` : ''}
        </p>
      </div>
    </section>
  );
}
