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
