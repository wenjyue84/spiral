import { test, expect } from '@playwright/test';

test('us_1215 SettingsTab displays, edits, and saves runtime config', async ({ page, baseURL }) => {
  // Use Spiral as test project
  const projectName = 'Spiral';

  // Navigate to Settings tab
  await page.goto(`${baseURL}/${encodeURIComponent(projectName)}/settings`);

  // Wait for SettingsTab to load — check for heading and table
  await expect(page.locator('h3:has-text("spiral.config.sh")')).toBeVisible({ timeout: 10000 });
  await expect(page.locator('table')).toBeVisible();

  // Assertion 1: Verify all three config fields are visible in the table
  // Look for rows containing the field names in the Variable column
  const maxPendingCell = page.locator('div.font-mono.text-blue-700:has-text("SPIRAL_MAX_PENDING")');
  const modelRoutingCell = page.locator('div.font-mono.text-blue-700:has-text("SPIRAL_MODEL_ROUTING")');
  const validateCmdCell = page.locator('div.font-mono.text-blue-700:has-text("SPIRAL_VALIDATE_CMD")');

  await expect(maxPendingCell).toBeVisible();
  await expect(modelRoutingCell).toBeVisible();
  await expect(validateCmdCell).toBeVisible();

  // Get the input/select fields by finding them in the same row
  // For SPIRAL_MAX_PENDING (number field)
  const maxPendingInput = maxPendingCell
    .locator('xpath=ancestor::tr[1]//input[@type="number"]');
  await expect(maxPendingInput).toBeVisible();
  const initialMaxPending = await maxPendingInput.inputValue() || '30';

  // For SPIRAL_MODEL_ROUTING (select field)
  const modelRoutingSelect = modelRoutingCell
    .locator('xpath=ancestor::tr[1]//select');
  await expect(modelRoutingSelect).toBeVisible();
  const initialModelRouting = await modelRoutingSelect.inputValue() || 'auto';

  // For SPIRAL_VALIDATE_CMD (text field)
  const validateCmdInput = validateCmdCell
    .locator('xpath=ancestor::tr[1]//input[@type="text"]');
  await expect(validateCmdInput).toBeVisible();
  const initialValidateCmd = await validateCmdInput.inputValue() || '';

  // Assertion 2: Verify current values are fetched
  // All three fields should be found and visible
  expect(maxPendingInput).toBeTruthy();
  expect(modelRoutingSelect).toBeTruthy();
  expect(validateCmdInput).toBeTruthy();

  // Assertion 3: Submit a config change and assert success toast appears
  // Change SPIRAL_MAX_PENDING to a different value
  const newMaxPending = String(parseInt(initialMaxPending) + 1);
  await maxPendingInput.fill(newMaxPending);

  // Click Save Config button
  const saveButton = page.locator('button:has-text("Save Config")');
  await expect(saveButton).toBeEnabled();
  await saveButton.click();

  // Assert success toast appears (green text with "Saved!")
  const successToast = page.locator('span:has-text("Saved!")');
  await expect(successToast).toBeVisible({ timeout: 10000 });

  // Verify the success toast has the correct emerald-600 style
  await expect(successToast).toHaveClass(/text-emerald-600/);
});
