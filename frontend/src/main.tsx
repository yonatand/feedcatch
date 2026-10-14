import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import './styles.css';

// Let env(safe-area-inset-*) report the notch / home-indicator insets (index.html is outside src/).
const vp = document.querySelector('meta[name="viewport"]');
if (vp && !/viewport-fit/.test(vp.getAttribute('content') ?? '')) {
  vp.setAttribute('content', `${vp.getAttribute('content') ?? 'width=device-width, initial-scale=1'}, viewport-fit=cover`);
}

const el = document.getElementById('root');
if (!el) throw new Error('#root element missing');

createRoot(el).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
