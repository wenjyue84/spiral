import { test, expect } from '@playwright/test';

// Configure the test to use localhost:5299 as the base URL
test.use({
  baseURL: 'http://localhost:5299',
  navigationTimeout: 30000,
  actionTimeout: 15000,
});

test.describe('SPIRAL Dashboard E2E Tests', () => {
  test('should display token burn rate widget with numeric value', async ({ page }) => {
    // Navigate to the dashboard
    await page.goto('/');

    // Wait for the page to stabilize
    await page.waitForLoadState('networkidle');

    // Find the burn-rate element
    const burnRateElement = page.locator('[data-testid="burn-rate"]');

    // Assert it's visible
    await expect(burnRateElement).toBeVisible();

    // Assert it contains numeric data (at least one digit)
    await expect(burnRateElement).toContainText(/\d+/);
  });

  test('should display story throughput chart with at least one data label', async ({ page }) => {
    // Navigate to the dashboard
    await page.goto('/');

    // Wait for the page to stabilize
    await page.waitForLoadState('networkidle');

    // Find the story-throughput element
    const throughputElement = page.locator('[data-testid="story-throughput"]');

    // Assert it's visible
    await expect(throughputElement).toBeVisible();

    // Assert it contains numeric data labels (percentage and counts)
    await expect(throughputElement).toContainText(/\d+/);

    // Verify it has at least one child element (the metric display)
    const childElements = throughputElement.locator('div');
    const count = await childElements.count();
    expect(count).toBeGreaterThan(0);
  });

  test('should display model escalation heatmap section', async ({ page }) => {
    // Navigate to the dashboard
    await page.goto('/');

    // Wait for the page to stabilize
    await page.waitForLoadState('networkidle');

    // Find the model-heatmap element
    const heatmapElement = page.locator('[data-testid="model-heatmap"]');

    // Assert it's visible
    await expect(heatmapElement).toBeVisible();

    // Assert it has the expected table structure for the heatmap
    const table = heatmapElement.locator('table');
    await expect(table).toBeVisible();
  });

  test('all dashboard sections should be visible together', async ({ page }) => {
    // Navigate to the dashboard
    await page.goto('/');

    // Wait for the page to stabilize
    await page.waitForLoadState('networkidle');

    // Check all three sections are visible simultaneously
    const burnRate = page.locator('[data-testid="burn-rate"]');
    const throughput = page.locator('[data-testid="story-throughput"]');
    const heatmap = page.locator('[data-testid="model-heatmap"]');

    // Verify all are visible
    await expect(burnRate).toBeVisible();
    await expect(throughput).toBeVisible();
    await expect(heatmap).toBeVisible();

    // Verify they contain content
    await expect(burnRate.locator('table')).toBeVisible();
    await expect(throughput).toContainText(/\d+/);
    await expect(heatmap.locator('table')).toBeVisible();
  });
});
