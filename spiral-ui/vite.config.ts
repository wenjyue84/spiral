import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import fs from 'node:fs'
import path from 'node:path'
import type { IncomingMessage, ServerResponse } from 'node:http'

// ── Spiral API plugin ──────────────────────────────────────────────────────────
// Provides two endpoints used by the "Save to Project" feature:
//   GET  /api/project  → { projectRoot }
//   POST /api/save-config { content, launchCommand } → writes spiral.config.sh
//
// Set SPIRAL_PROJECT_ROOT env var when starting the server so the API knows
// which project directory to write to.
//   SPIRAL_PROJECT_ROOT="C:/my-project" npm run dev -- --port 5299

function spiralApiPlugin() {
  const PROJECT_ROOT = process.env.SPIRAL_PROJECT_ROOT || process.cwd();

  return {
    name: 'spiral-api',
    configureServer(server: { middlewares: { use: (path: string, fn: (req: IncomingMessage, res: ServerResponse, next: () => void) => void) => void } }) {
      // GET /api/project — returns project root so the UI can show it
      server.middlewares.use('/api/project', (req, res, next) => {
        if (req.method !== 'GET') { next(); return; }
        res.setHeader('Content-Type', 'application/json');
        res.setHeader('Access-Control-Allow-Origin', '*');
        res.end(JSON.stringify({ projectRoot: PROJECT_ROOT }));
      });

      // POST /api/save-config — writes spiral.config.sh to projectRoot
      server.middlewares.use('/api/save-config', (req, res, next) => {
        if (req.method !== 'POST') { next(); return; }
        let body = '';
        req.on('data', (chunk: Buffer) => { body += chunk.toString(); });
        req.on('end', () => {
          try {
            const { content } = JSON.parse(body) as { content: string };
            const configPath = path.join(PROJECT_ROOT, 'spiral.config.sh');
            fs.writeFileSync(configPath, content, 'utf8');
            res.setHeader('Content-Type', 'application/json');
            res.setHeader('Access-Control-Allow-Origin', '*');
            res.end(JSON.stringify({ ok: true, path: configPath }));
          } catch (e) {
            res.statusCode = 500;
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify({ error: String(e) }));
          }
        });
      });
    },
  };
}

export default defineConfig({
  plugins: [
    tailwindcss(),
    react(),
    spiralApiPlugin(),
  ],
})
