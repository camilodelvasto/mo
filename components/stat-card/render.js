// components/stat-card/render.js
// Renders: oversized number, description label, optional gradient progress bar.
// Reads --bar-gradient-from and --bar-gradient-to from the active theme.
// Throws if required data fields are missing.

export function render(data, themeData) {
  if (!data.stat) throw new Error('stat-card: stat field is required');
  if (!data.label) throw new Error('stat-card: label field is required');

  const root = document.createElement('div');
  root.dataset.component = 'stat-card';

  const stat = document.createElement('p');
  stat.className = 'stat-card-stat';
  stat.textContent = String(data.stat);
  root.appendChild(stat);

  const label = document.createElement('p');
  label.className = 'stat-card-label';
  label.textContent = String(data.label);
  root.appendChild(label);

  if (data.bar != null) {
    const barTrack = document.createElement('div');
    barTrack.className = 'stat-card-bar-track';

    const barFill = document.createElement('div');
    barFill.className = 'stat-card-bar-fill';
    barFill.style.width = `${Math.min(100, Math.max(0, Number(data.bar)))}%`;

    barTrack.appendChild(barFill);
    root.appendChild(barTrack);
  }

  const frag = document.createDocumentFragment();
  frag.appendChild(root);
  return frag;
}
