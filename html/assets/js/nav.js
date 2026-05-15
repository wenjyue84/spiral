// Shared nav + dark mode toggle + active-link highlighting.
// Each page calls renderShell({page: 'quick-start'}) on page load.

const NAV_LINKS = [
  { id: 'dashboard',        label: 'Dashboard',        href: 'index.html',                    top: true },
  { id: 'introduction',     label: 'Introduction',     href: 'pages/01-introduction.html' },
  { id: 'quick-start',      label: 'Quick Start',      href: 'pages/02-quick-start.html' },
  { id: 'architecture',     label: 'Architecture',     href: 'pages/03-architecture.html' },
  { id: 'phase-deep-dive',  label: 'Phase Deep Dive',  href: 'pages/04-phase-deep-dive.html' },
  { id: 'cli-reference',    label: 'CLI Reference',    href: 'pages/05-cli-reference.html' },
  { id: 'configuration',    label: 'Configuration',    href: 'pages/06-configuration.html' },
  { id: 'examples',         label: 'Examples & Recipes', href: 'pages/07-examples-and-recipes.html' },
  { id: 'glossary',         label: 'Glossary',         href: 'pages/08-glossary.html' },
  { id: 'troubleshooting',  label: 'Troubleshooting',  href: 'pages/09-troubleshooting.html' },
];

function isSubpage() {
  return window.location.pathname.includes('/pages/');
}

function relHref(href) {
  if (isSubpage()) {
    if (href === 'index.html') return '../index.html';
    if (href.startsWith('pages/')) return href.replace('pages/', '');
  }
  return href;
}

function renderShell({ page }) {
  const d = window.ATP_DATA;
  const themeInit = localStorage.getItem('spiral-html-theme') || 'light';
  document.documentElement.dataset.theme = themeInit;

  const sidebar = document.getElementById('sidebar');
  if (sidebar) {
    sidebar.innerHTML = `
      <h1>${d.project.name}</h1>
      <div class="subtitle">${d.project.customer}</div>
      <nav>
        ${NAV_LINKS.map(l => `
          <a href="${relHref(l.href)}" class="${page === l.id ? 'active' : ''}" data-page="${l.id}">
            ${l.label}
          </a>
        `).join('')}
      </nav>
      <div class="footer">
        <span class="badge neutral">${d.project.status}</span><br>
        Updated ${d.project.lastUpdated}<br>
      </div>
    `;
  }

  const tt = document.getElementById('themeToggle');
  if (tt) {
    const sync = () => tt.textContent = (document.documentElement.dataset.theme === 'dark' ? 'Light mode' : 'Dark mode');
    sync();
    tt.addEventListener('click', () => {
      const cur = document.documentElement.dataset.theme;
      const next = cur === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = next;
      localStorage.setItem('spiral-html-theme', next);
      sync();
      if (window.__onThemeChange) window.__onThemeChange(next);
    });
  }
}

// Helpers
function badgeFor(status) {
  const s = status.toLowerCase();
  if (s.includes('passed') || s === 'done') return `<span class="badge good">${status}</span>`;
  if (s === 'failed' || s === 'blocked') return `<span class="badge bad">${status}</span>`;
  if (s === 'active' || s === 'running') return `<span class="badge warn">${status}</span>`;
  if (s === 'pending' || s === 'upcoming') return `<span class="badge neutral">${status}</span>`;
  return `<span class="badge">${status}</span>`;
}
