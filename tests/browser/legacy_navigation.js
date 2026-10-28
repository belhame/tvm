import { expect } from '@playwright/test';

// Scenarios navigate explicitly to the workspace they exercise. The quick
// intake suite also verifies the actual default dashboard landing page.
export async function openLegacyDashboard(page) {
  const metric = page.locator('.metric-value').first();
  if (await metric.isVisible()) {
    await expect(metric).toContainText(/\d/);
    return;
  }
  const navigation = page.getByRole('navigation', { name: 'Navigation principale', exact: true });
  await expect(navigation).toBeAttached();
  // A transformed mobile sidebar is still CSS-visible to Playwright even
  // while it sits outside the viewport. Its explicit menu button is the
  // responsive-layout signal; the navigation's visibility is not sufficient.
  const openMenu = page.getByRole('button', { name: 'Ouvrir le menu', exact: true });
  if (await openMenu.isVisible() && !await page.locator('.sidebar.open').count()) {
    await openMenu.click();
  }
  await navigation.getByRole('button', { name: 'Tableau de bord', exact: true }).click();
  await expect(metric).toContainText(/\d/);
}

export async function openRequestsWorkspace(page) {
  const heading = page.getByRole('heading', { name: 'Demandes SAV', exact: true });
  if (await heading.isVisible()) return;
  const navigation = page.getByRole('navigation', { name: 'Navigation principale', exact: true });
  await expect(navigation).toBeAttached();
  const openMenu = page.getByRole('button', { name: 'Ouvrir le menu', exact: true });
  if (await openMenu.isVisible() && !await page.locator('.sidebar.open').count()) {
    await openMenu.click();
  }
  await navigation.getByRole('button', { name: 'Demandes SAV', exact: true }).click();
  await expect(heading).toBeVisible();
}

export async function confirmCurrentAssignment(page, requestId) {
  const sessionResponse = await page.request.get('/api/session/');
  expect(sessionResponse.ok()).toBeTruthy();
  const session = await sessionResponse.json();
  const currentResponse = await page.request.get(`/api/requests/${requestId}/`);
  expect(currentResponse.ok()).toBeTruthy();
  const current = await currentResponse.json();
  expect(current.assignment.technician).toBe(session.user.id);
  const response = await page.request.post(`/api/requests/${requestId}/assignment/confirm/`, {
    headers: { 'X-CSRFToken': session.csrfToken },
    data: { expected_revision: current.assignment.revision, accept: true },
  });
  expect(response.status(), await response.text()).toBe(200);
  const accepted = await response.json();
  expect(accepted.assignment.accepted).toBe(true);
  return accepted;
}

export async function acceptCurrentOutboundMission(page, card, job) {
  await card.getByRole('button', { name: 'Accepter la mission', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Accepter la mission', exact: true });
  await expect(dialog).toContainText(job.call_number);
  const saved = page.waitForResponse(result =>
    new URL(result.url()).pathname === `/api/logistics/outbound/${job.id}/accept/`
    && result.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Oui', exact: true }).click();
  const result = await saved;
  expect(result.status(), await result.text()).toBe(200);
  const accepted = await result.json();
  expect(accepted.accepted).toBe(true);
  expect(accepted.accepted_revision).toBe(accepted.assignment_revision);
  expect(accepted.assigned_courier).toBe(job.assigned_courier);
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole('dialog', { name: 'Mission acceptée', exact: true })).toHaveCount(0);
  return accepted;
}
