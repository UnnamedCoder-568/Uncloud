import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { inDesktop } from './lib/platform'
import { initialiseAppearance } from './lib/appearance'

// The chassis clears the traffic lights and makes the title bar draggable;
// neither exists in a browser, and this is how the stylesheet knows.
if (!inDesktop()) document.documentElement.dataset.surface = 'web'
initialiseAppearance()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
