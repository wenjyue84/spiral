import { test, expect, Page } from '@playwright/test';

const BASE_URL = 'http://localhost:5299';

async function navigateToTestsTab(page: Page, projectName: string = 'test-project') {
  await page.goto(`${BASE_URL}/${encodeURIComponent(projectName)}/tests`);
  await page.waitForLoadState('networkidle');
}

async function mockTestHistoryEndpoint(page: Page) {
  // Mock the /api/tests/history endpoint with sample data
  await page.route('**/api/tests/history*', async route => {
    const mockData = {
      entries: [
        {
          id: 'test-1',
          date: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString(), // 2 days ago
          testFile: 'tests/e2e/test-workflow.spec.ts',
          status: 'passed' as const,
          coverage: 92,
          output: 'All tests passed in 5.2s',
        },
        {
          id: 'test-2',
          date: new Date(Date.now() - 1 * 24 * 60 * 60 * 1000).toISOString(), // 1 day ago
          testFile: 'tests/e2e/test-dashboard.spec.ts',
          status: 'failed' as const,
          coverage: 87,
          output: 'Test failed: expected true but got false',
        },
        {
          id: 'test-3',
          date: new Date().toISOString(), // today
          testFile: 'tests/unit/test-utils.spec.ts',
          status: 'passed' as const,
          coverage: 95,
          output: 'All unit tests passed',
        },
      ],
    };
    await route.fulfill({ json: mockData });
  });
}

test.describe('Tests Tab', () => {
  test.beforeEach(async ({ page }) => {
    // Mock the project data endpoint
    await page.route('**/api/project-live*', async route => {
      const mockData = {
        name: 'test-project',
        root: '/test/project',
        progress: {
          done: 10,
          pending: 5,
          total: 15,
          productName: 'Test Project',
        },
        activeStatus: null,
        lastCompletedStory: null,
        checkpointTs: null,
        lastLogModified: null,
        progressHistory: [],
        storyAttempts: {},
        tokenBurn: [],
        config: {},
        activity: [],
        constitution: '',
      };
      await route.fulfill({ json: mockData });
    });

    await mockTestHistoryEndpoint(page);
  });

  test('renders table with Date, Test File, Status, Coverage % columns', async ({ page }) => {
    await navigateToTestsTab(page);

    // Verify table headers are present
    const headers = ['Date', 'Test File', 'Status', 'Coverage %'];
    for (const header of headers) {
      await expect(page.locator('th')).containsText(header);
    }

    // Verify table rows are rendered
    await expect(page.locator('tbody tr').first()).toBeVisible();

    // Verify all three test entries are visible
    await expect(page.locator('text=test-workflow.spec.ts')).toBeVisible();
    await expect(page.locator('text=test-dashboard.spec.ts')).toBeVisible();
    await expect(page.locator('text=test-utils.spec.ts')).toBeVisible();

    // Verify coverage percentages
    await expect(page.locator('text=92%')).toBeVisible();
    await expect(page.locator('text=87%')).toBeVisible();
    await expect(page.locator('text=95%')).toBeVisible();

    // Verify status badges
    await expect(page.locator('text=✓ Passed')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=✗ Failed')).toBeVisible({ timeout: 5000 });
  });

  test('date filter buttons update results and re-render trend chart', async ({ page }) => {
    await navigateToTestsTab(page);

    // Verify initial date range button state
    const button7d = page.locator('button:has-text("Last 7 days")').first();
    const button30d = page.locator('button:has-text("Last 30 days")').first();

    // Verify 30d is selected by default
    await expect(button30d).toHaveClass(/bg-blue-600/);

    // Click 7d button
    await button7d.click();
    await page.waitForLoadState('networkidle');

    // Verify 7d is now selected
    await expect(button7d).toHaveClass(/bg-blue-600/);

    // Verify chart is still visible
    await expect(page.locator('text=Pass Rate Trend')).toBeVisible();

    // Verify query includes days parameter
    await page.route('**/api/tests/history*', async route => {
      const url = new URL(route.request().url());
      expect(url.searchParams.get('days')).toBe('7');
      await route.abort();
    });

    // Click 7d again to trigger another request
    await button7d.click();
  });

  test('clicking table row expands to show pytest output', async ({ page }) => {
    await navigateToTestsTab(page);

    // Find a row with output
    const testRow = page.locator('tbody tr').first();
    const expandButton = testRow.locator('button');

    // Initially, output should not be visible
    let outputRow = page.locator('text=All tests passed in 5.2s');
    await expect(outputRow).not.toBeVisible();

    // Click expand button
    await expandButton.click();

    // Output should now be visible
    await expect(outputRow).toBeVisible({ timeout: 5000 });

    // Verify the output is in a code block
    const preBlock = page.locator('pre').filter({ hasText: 'All tests passed' });
    await expect(preBlock).toBeVisible();

    // Click again to collapse
    await expandButton.click();

    // Output should now be hidden
    await expect(outputRow).not.toBeVisible();
  });

  test('trend chart displays pass rate over time', async ({ page }) => {
    await navigateToTestsTab(page);

    // Verify chart title is present
    await expect(page.locator('text=Pass Rate Trend')).toBeVisible();

    // Verify chart canvas/SVG is rendered
    const chartContainer = page.locator('div').filter({ has: page.locator('svg') });
    await expect(chartContainer).toBeVisible();
  });
});
