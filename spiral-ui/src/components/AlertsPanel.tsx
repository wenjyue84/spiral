/**
 * spiral-ui/src/components/AlertsPanel.tsx — Real-time alert display component
 * Subscribes to /ws/alerts WebSocket and displays cost threshold alerts
 */

import React, { useEffect, useState, useRef } from 'react';

interface Alert {
  type: 'cost_alert';
  severity: 'warning' | 'critical';
  current_cost: number;
  ceiling: number;
  percent_used: number;
  timestamp: string;
  id?: string; // Auto-generated for deduplication
}

interface DisplayAlert extends Alert {
  id: string;
  displayTime: number; // Time when alert was added (for auto-dismiss)
}

const ALERT_DISPLAY_DURATION_MS = 10000; // 10 seconds
const WS_RECONNECT_DELAY_MS = 3000; // 3 seconds
const WS_URL = `ws://${window.location.hostname}:${window.location.port || 5299}/ws/alerts`;

export const AlertsPanel: React.FC = () => {
  const [alerts, setAlerts] = useState<DisplayAlert[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>();
  const dismissTimeoutsRef = useRef<Map<string, NodeJS.Timeout>>(new Map());

  // Parse port from environment or window location
  const getWebSocketURL = (): string => {
    const port = process.env.REACT_APP_DASHBOARD_PORT || '5299';
    return `ws://localhost:${port}/ws/alerts`;
  };

  // Connect to WebSocket
  const connectWebSocket = () => {
    try {
      const ws = new WebSocket(getWebSocketURL());

      ws.onopen = () => {
        console.log('[AlertsPanel] Connected to /ws/alerts');
        setIsConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const alert = JSON.parse(event.data) as Alert;

          if (alert.type === 'cost_alert') {
            // Generate unique ID to prevent duplicate alerts
            const alertId = `${alert.severity}_${alert.timestamp}_${alert.percent_used}`;

            // Check if this alert already exists
            if (alerts.some((a) => a.id === alertId)) {
              return;
            }

            const displayAlert: DisplayAlert = {
              ...alert,
              id: alertId,
              displayTime: Date.now(),
            };

            setAlerts((prev) => [...prev, displayAlert]);

            // Schedule auto-dismiss after 10 seconds
            const timeout = setTimeout(() => {
              dismissAlert(alertId);
            }, ALERT_DISPLAY_DURATION_MS);

            dismissTimeoutsRef.current.set(alertId, timeout);
          }
        } catch (e) {
          console.error('[AlertsPanel] Failed to parse message:', event.data, e);
        }
      };

      ws.onclose = () => {
        console.log('[AlertsPanel] Disconnected from /ws/alerts');
        setIsConnected(false);

        // Attempt to reconnect
        reconnectTimeoutRef.current = setTimeout(connectWebSocket, WS_RECONNECT_DELAY_MS);
      };

      ws.onerror = (event) => {
        console.error('[AlertsPanel] WebSocket error:', event);
        setIsConnected(false);
      };

      wsRef.current = ws;
    } catch (e) {
      console.error('[AlertsPanel] Failed to connect:', e);
      reconnectTimeoutRef.current = setTimeout(connectWebSocket, WS_RECONNECT_DELAY_MS);
    }
  };

  // Dismiss alert by ID
  const dismissAlert = (alertId: string) => {
    setAlerts((prev) => prev.filter((a) => a.id !== alertId));

    // Clear any pending timeout
    const timeout = dismissTimeoutsRef.current.get(alertId);
    if (timeout) {
      clearTimeout(timeout);
      dismissTimeoutsRef.current.delete(alertId);
    }
  };

  // Initialize WebSocket connection
  useEffect(() => {
    connectWebSocket();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      // Clear all dismiss timeouts
      dismissTimeoutsRef.current.forEach((timeout) => clearTimeout(timeout));
    };
  }, []);

  const getSeverityStyles = (severity: 'warning' | 'critical') => {
    if (severity === 'critical') {
      return {
        bg: '#fee2e2',
        border: '#dc2626',
        text: '#991b1b',
        badge: '#dc2626',
      };
    } else {
      // warning
      return {
        bg: '#fef3c7',
        border: '#f59e0b',
        text: '#92400e',
        badge: '#f59e0b',
      };
    }
  };

  return (
    <div
      style={{
        position: 'fixed',
        bottom: '20px',
        right: '20px',
        zIndex: 9999,
        maxWidth: '400px',
      }}
    >
      {/* Connection status indicator */}
      <div
        style={{
          marginBottom: '10px',
          fontSize: '12px',
          color: isConnected ? '#059669' : '#dc2626',
          textAlign: 'right',
        }}
      >
        {isConnected ? '● Connected' : '● Disconnected'}
      </div>

      {/* Alerts stack */}
      {alerts.map((alert) => {
        const styles = getSeverityStyles(alert.severity);
        const timeElapsed = Date.now() - alert.displayTime;
        const progress = Math.min(100, (timeElapsed / ALERT_DISPLAY_DURATION_MS) * 100);

        return (
          <div
            key={alert.id}
            onClick={() => dismissAlert(alert.id)}
            style={{
              backgroundColor: styles.bg,
              border: `2px solid ${styles.border}`,
              borderRadius: '6px',
              padding: '12px',
              marginBottom: '10px',
              cursor: 'pointer',
              fontFamily: 'system-ui, -apple-system, sans-serif',
              color: styles.text,
              boxShadow: '0 4px 6px rgba(0, 0, 0, 0.1)',
            }}
          >
            {/* Header with severity badge and timestamp */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
              <span
                style={{
                  display: 'inline-block',
                  padding: '2px 8px',
                  backgroundColor: styles.badge,
                  color: 'white',
                  borderRadius: '3px',
                  fontSize: '11px',
                  fontWeight: 'bold',
                  textTransform: 'uppercase',
                }}
              >
                {alert.severity}
              </span>
              <span style={{ fontSize: '12px', opacity: 0.7 }}>
                {new Date(alert.timestamp).toLocaleTimeString()}
              </span>
            </div>

            {/* Cost information */}
            <div style={{ marginBottom: '6px' }}>
              <div style={{ fontSize: '13px', fontWeight: 'bold' }}>
                Cost: ${alert.current_cost.toFixed(2)} / ${alert.ceiling.toFixed(2)}
              </div>
              <div style={{ fontSize: '12px', opacity: 0.8 }}>
                {alert.percent_used.toFixed(1)}% of ceiling
              </div>
            </div>

            {/* Auto-dismiss progress bar */}
            <div
              style={{
                height: '3px',
                backgroundColor: 'rgba(0, 0, 0, 0.1)',
                borderRadius: '2px',
                overflow: 'hidden',
                marginTop: '8px',
              }}
            >
              <div
                style={{
                  height: '100%',
                  backgroundColor: styles.badge,
                  width: `${100 - progress}%`,
                  transition: 'width 0.1s linear',
                }}
              />
            </div>

            {/* Dismiss hint */}
            <div
              style={{
                fontSize: '11px',
                opacity: 0.6,
                marginTop: '4px',
                textAlign: 'right',
              }}
            >
              Click to dismiss
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default AlertsPanel;
