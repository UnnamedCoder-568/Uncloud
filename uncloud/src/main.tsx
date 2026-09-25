import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { ScreenBoundary } from './components/Panes'
import { inDesktop } from './lib/platform'
import { initialiseAppearance } from './lib/appearance'
import { interceptExternalLinks } from './lib/links'

// The chassis clears the traffic lights and makes the title bar draggable;
// neither exists in a browser, and this is how the stylesheet knows.
if (!inDesktop()) document.documentElement.dataset.surface = 'web'
// Close disclosures consistently on outside interaction or Escape.
document.addEventListener('pointerdown', (event) => {
  document.querySelectorAll<HTMLDetailsElement>('details[open]').forEach((menu) => {
    if (event.target instanceof Node && !menu.contains(event.target)) menu.open = false
  })
})
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') document.querySelectorAll<HTMLDetailsElement>('details[open]').forEach((menu) => { menu.open = false })
})
initialiseAppearance()
interceptExternalLinks()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {/* Last resort: a failure outside any screen still gets a way back. */}
    <ScreenBoundary whole>
      <App />
    </ScreenBoundary>
  </StrictMode>,
)
