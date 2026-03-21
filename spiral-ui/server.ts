#!/usr/bin/env node
/**
 * spiral-ui/server.ts — WebSocket server for real-time SPIRAL alerts
 * Exposes GET /ws/alerts WebSocket endpoint for streaming cost alerts
 */

import express, { Express } from 'express';
import { WebSocketServer, WebSocket } from 'ws';
import { createServer } from 'http';
import { readFileSync, watch } from 'fs';
import { join, resolve } from 'path';
import { existsSync } from 'fs';

interface CostAlert {
  type: 'cost_alert';
  severity: 'warning' | 'critical';
  current_cost: number;
  ceiling: number;
  percent_used: number;
  timestamp: string;
}

const PORT = process.env.SPIRAL_DASHBOARD_PORT || 5299;
const ALERTS_QUEUE_FILE = join(resolve('.'), '.spiral', 'alerts.jsonl');

const app: Express = express();
const server = createServer(app);
const wss = new WebSocketServer({ server, path: '/ws/alerts' });

// Track connected clients
const clients = new Set<WebSocket>();

// Parse and broadcast alerts from file
function processAlertQueue() {
  try {
    if (!existsSync(ALERTS_QUEUE_FILE)) {
      return;
    }

    const content = readFileSync(ALERTS_QUEUE_FILE, 'utf-8');
    const lines = content.trim().split('\n').filter(line => line.length > 0);

    for (const line of lines) {
      try {
        const alert = JSON.parse(line) as CostAlert;
        broadcastAlert(alert);
      } catch (e) {
        console.error('Failed to parse alert:', line, e);
      }
    }

    // Clear the queue after processing
    readFileSync(ALERTS_QUEUE_FILE, 'utf-8');
  } catch (e) {
    // File might not exist or be empty, which is fine
  }
}

// Broadcast alert to all connected clients
function broadcastAlert(alert: CostAlert) {
  const message = JSON.stringify(alert);
  let disconnected: WebSocket[] = [];

  for (const client of clients) {
    if (client.readyState === WebSocket.OPEN) {
      client.send(message);
    } else {
      disconnected.push(client);
    }
  }

  // Clean up disconnected clients
  for (const client of disconnected) {
    clients.delete(client);
  }
}

// WebSocket connection handler
wss.on('connection', (ws: WebSocket) => {
  clients.add(ws);
  console.log(`[${new Date().toISOString()}] Client connected. Total: ${clients.size}`);

  ws.on('close', () => {
    clients.delete(ws);
    console.log(`[${new Date().toISOString()}] Client disconnected. Total: ${clients.size}`);
  });

  ws.on('error', (err) => {
    console.error('WebSocket error:', err);
    clients.delete(ws);
  });
});

// HTTP health check endpoint
app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString(), clients: clients.size });
});

// Escalation breakdown endpoint (US-646)
app.get('/api/dashboard/escalation-breakdown', (req, res) => {
  const escalationsFile = join(resolve('.'), '.spiral', 'escalations.json');

  try {
    if (!existsSync(escalationsFile)) {
      // Return empty breakdown if no escalations yet
      return res.json({
        token_limit: 0,
        syntax_error: 0,
        timeout: 0,
        api_error: 0,
        total_escalations: 0
      });
    }

    const content = readFileSync(escalationsFile, 'utf-8');
    const escalations = JSON.parse(content) as Array<{ reason: string }>;

    // Count by reason code
    const breakdown: Record<string, number> = {
      token_limit: 0,
      syntax_error: 0,
      timeout: 0,
      api_error: 0
    };

    for (const entry of escalations) {
      const reason = entry.reason || 'api_error';
      if (reason in breakdown) {
        breakdown[reason]++;
      }
    }

    res.json({
      token_limit: breakdown.token_limit,
      syntax_error: breakdown.syntax_error,
      timeout: breakdown.timeout,
      api_error: breakdown.api_error,
      total_escalations: escalations.length
    });
  } catch (e) {
    console.error('[escalation-breakdown] Error reading escalations.json:', e);
    res.status(500).json({ error: 'Failed to read escalation data' });
  }
});

// Worker swimlane visualization data endpoint (US-652)
app.get('/api/dashboard/worker-swimlanes', (req, res) => {
  const traceFile = join(resolve('.'), '.spiral', 'phase-trace-data.json');

  try {
    if (!existsSync(traceFile)) {
      return res.json([]);
    }

    const content = readFileSync(traceFile, 'utf-8');
    const traceData = JSON.parse(content) as { iterations: Array<{ iter: number; phases: Array<any> }> };

    // Format swimlane data: worker_id 0, per-iteration phases with duration
    const swimlanes: Array<{
      worker_id: number;
      iteration: number;
      phases: Array<{
        phase_name: string;
        duration_ms: number;
        start_time: string;
        status: string;
      }>;
    }> = [];

    for (const iterData of traceData.iterations || []) {
      const phases = [];
      for (const phaseData of iterData.phases || []) {
        const label = phaseData.label || '';
        const lines = phaseData.lines || [];
        const duration_ms = Math.max(50, lines.length * 100);
        const status = label.includes('Skipping') ? 'skipped' : 'success';

        phases.push({
          phase_name: phaseData.phase || 'UNKNOWN',
          duration_ms,
          start_time: new Date().toISOString(),
          status
        });
      }

      if (phases.length > 0) {
        swimlanes.push({
          worker_id: 0,
          iteration: iterData.iter || 0,
          phases
        });
      }
    }

    res.json(swimlanes);
  } catch (e) {
    console.error('[worker-swimlanes] Error loading phase trace:', e);
    res.status(500).json({ error: 'Failed to read phase trace data' });
  }
});

// Start server
server.listen(PORT, () => {
  console.log(`[${new Date().toISOString()}] SPIRAL WebSocket server listening on port ${PORT}`);
  console.log(`[${new Date().toISOString()}] WebSocket endpoint: ws://localhost:${PORT}/ws/alerts`);
});

// Watch alerts queue for new messages
if (existsSync(join(resolve('.'), '.spiral'))) {
  watch(
    join(resolve('.'), '.spiral'),
    { recursive: false },
    (eventType, filename) => {
      if (filename === 'alerts.jsonl') {
        processAlertQueue();
      }
    }
  );

  // Process any pending alerts on startup
  processAlertQueue();
}

// Graceful shutdown
process.on('SIGINT', () => {
  console.log(`\n[${new Date().toISOString()}] Shutting down gracefully...`);
  wss.close(() => {
    server.close(() => {
      process.exit(0);
    });
  });
});
