import React from 'react';
import ReactDOM from 'react-dom/client';
import 'leaflet/dist/leaflet.css';
import App from './App';
import './styles.css';
import { loadRuntimeConfig, resolveCompanionBaseUrl } from './runtimeConfig';

async function bootstrap() {
  const runtimeConfig = await loadRuntimeConfig();
  const defaultCompanionBaseUrl = resolveCompanionBaseUrl(runtimeConfig);

  ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
    <React.StrictMode>
      <App defaultCompanionBaseUrl={defaultCompanionBaseUrl} runtimeConfig={runtimeConfig} />
    </React.StrictMode>,
  );
}

void bootstrap();
