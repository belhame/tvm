import { test, expect } from '@playwright/test';
import { openLegacyDashboard } from './legacy_navigation.js';

const password = process.env.TVM_DEMO_PASSWORD;

async function login(page, username = 'admin', courier = false) {
  if (!password) throw new Error('TVM_DEMO_PASSWORD requis ; utiliser bash scripts/e2e.sh.');
  await page.goto('/');
  await page.getByLabel('Identifiant', { exact: true }).fill(username);
  await page.getByLabel('Mot de passe', { exact: true }).fill(password);
  const path = courier ? '/api/logistics/bootstrap/' : '/api/dashboard/';
  const loaded = page.waitForResponse(result => new URL(result.url()).pathname === path && result.ok());
  await page.getByRole('button', { name: /Se connecter/i }).click();
  await loaded;
  if (courier) await expect(page.getByRole('navigation', { name: 'Navigation livreur', exact: true })).toBeVisible();
  else await openLegacyDashboard(page);
}

async function response(page, path, method = 'GET', data) {
  const { csrfToken } = await (await page.request.get('/api/session/')).json();
  return page.request.fetch(`/api/${path}`, { method, data, headers: { 'X-CSRFToken': csrfToken } });
}

async function api(page, path, method = 'GET', data) {
  const result = await response(page, path, method, data);
  expect(result.ok(), `${method} ${path} → ${result.status()}: ${await result.text()}`).toBeTruthy();
  return result.json();
}

async function navigate(page, label) {
  const navigation = page.getByRole('navigation', { name: 'Navigation principale' });
  if (!await navigation.isVisible()) await page.getByRole('button', { name: 'Ouvrir le menu', exact: true }).click();
  await navigation.getByText(label, { exact: true }).click();
}

function filteredJournal(page, client, state = '', channel = '') {
  return page.waitForResponse(result => {
    const url = new URL(result.url());
    return url.pathname === '/api/logistics/outbox/' && url.searchParams.get('client') === String(client)
      && (url.searchParams.get('state') || '') === state && (url.searchParams.get('channel') || '') === channel && result.ok();
  });
}

function marker(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

test('le journal client prévisualise les vrais messages e-mail et WhatsApp, masque les destinataires et maintient toute relance bloquée sans fournisseur activé', async ({ page, browser }) => {
  test.setTimeout(180000);
  await login(page);
  // Verify the isolated test server is disabled before creating any opt-in event.
  // This scenario never configures credentials or enables an external channel.
  const globalChannels = await api(page, 'logistics/channels/');
  expect(globalChannels.email).toMatchObject({ enabled: false, operational: false, status: 'disabled' });
  expect(globalChannels.whatsapp).toMatchObject({ enabled: false, operational: false, status: 'disabled' });
  const tag = marker('journal-fictif');
  const email = `responsable-${Date.now()}@example.invalid`;
  const phone = '+12025550127'; // Reserved fictional 202-555-0127, not a real recipient.
  const company = await api(page, 'clients/', 'POST', {
    name: `Centre de notification fictif ${tag}`, contact_name: 'Responsable fictif du centre', email, phone,
    address: '27 voie du centre de notification fictif', notify_email: true, notify_whatsapp: true,
    notes: `NOTE-CLIENT-INTERNE-${tag}`,
  });
  const internal = await api(page, 'users/', 'POST', {
    username: `livreur-journal-${tag}`, first_name: 'Livreur fictif du journal', role: 'courier', courier_kind: 'internal', password,
  });
  await api(page, `clients/${company.id}/`, 'PATCH', { internal_courier: internal.id });
  const equipment = await api(page, 'equipment/', 'POST', {
    client: company.id, serial_number: `JOURNAL-SN-000027-${tag}`, model: 'Onduleur fictif du journal', brand: 'Eaton',
  });
  const request = await api(page, 'requests/', 'POST', {
    equipment: equipment.id, subject: `Contrôle de notification fictif ${tag}`, status: 'testing',
    client_reference: `000-CLIENT-JOURNAL-${tag}`, description: `DIAGNOSTIC-NON-INCLUS-${tag}`,
  });
  const { as_of: today } = await api(page, 'requests/categories/');
  await api(page, `requests/${request.id}/disposition/repair/`, 'POST', {
    diagnosis: 'Tests de fonctionnement fictifs réussis, matériel prêt au transport.', tests_passed: true, tested_on: today,
  });
  const query = `logistics/outbox/?client=${company.id}`;
  const initial = await api(page, query);
  expect(initial.results).toHaveLength(2);
  expect(initial.results.map(entry => entry.channel).sort()).toEqual(['email', 'whatsapp']);
  expect(initial.counts.blocked).toBe(2);
  expect(initial.counts.sent).toBe(0);
  for (const entry of initial.results) {
    expect(entry).toMatchObject({ client: { id: company.id }, event: 'transport_assigned', state: 'blocked', blocked_reason: 'channel_disabled', attempts: 0, sent_at: null, can_retry: true });
    expect(entry.recipient_redacted).toContain('***');
    expect(entry.recipient_redacted).not.toBe(entry.channel === 'email' ? email : phone);
    expect(entry.provider_status).not.toBe('accepted');
  }

  const reloaded = page.waitForResponse(result => new URL(result.url()).pathname === '/api/dashboard/' && result.ok());
  await page.reload();
  await reloaded;
  await openLegacyDashboard(page);
  await navigate(page, 'WhatsApp & assistant IA');
  const journal = page.getByRole('region', { name: 'Journal des notifications client', exact: true });
  await expect(journal).toBeVisible();
  const clientFiltered = filteredJournal(page, company.id);
  await journal.getByRole('combobox', { name: 'Société des notifications', exact: true }).selectOption(String(company.id));
  await clientFiltered;
  const stateFiltered = filteredJournal(page, company.id, 'blocked');
  await journal.getByRole('combobox', { name: 'État des notifications client', exact: true }).selectOption('blocked');
  await stateFiltered;
  await expect(journal.locator('tbody tr')).toHaveCount(2);
  await expect(journal.locator('.notification-outbox-counts')).toContainText('Bloquée : 2');
  const channels = journal.getByRole('region', { name: 'Canaux de notification client', exact: true });
  await expect(channels.locator('.notification-channel-card')).toHaveCount(2);
  await expect(channels.getByText('Canal désactivé côté serveur', { exact: true })).toHaveCount(2);
  await expect(channels.getByText('Autorisées pour cette société', { exact: true })).toHaveCount(2);
  await expect(journal).not.toContainText('Acceptée le ');

  for (const entry of initial.results) {
    const channelFiltered = filteredJournal(page, company.id, 'blocked', entry.channel);
    await journal.getByRole('combobox', { name: 'Canal des notifications client', exact: true }).selectOption(entry.channel);
    await channelFiltered;
    const row = journal.locator('tbody tr');
    await expect(row).toHaveCount(1);
    await expect(row).toContainText(entry.channel === 'email' ? 'E-mail' : 'WhatsApp');
    await expect(row).toContainText('Bloquée');
    await expect(row).toContainText('0 tentative(s)');
    await expect(row).toContainText(entry.recipient_redacted);
    const previewLoaded = page.waitForResponse(result => new URL(result.url()).pathname === `/api/logistics/outbox/${entry.id}/preview/` && result.request().method() === 'GET');
    await row.getByRole('button', { name: 'Prévisualiser avant relance', exact: true }).click();
    const previewResponse = await previewLoaded;
    expect(previewResponse.ok(), await previewResponse.text()).toBe(true);
    const preview = await previewResponse.json();
    expect(preview.notification).toMatchObject({ id: entry.id, state: 'blocked', attempts: 0, sent_at: null });
    expect(preview.preview).toMatchObject({ call_number: request.call_number || request.reference, client_reference: request.client_reference, serial_number: equipment.serial_number, recipient_redacted: entry.recipient_redacted });
    expect(preview.preview_token).toBeTruthy();
    expect(preview.warnings).toContain('channel_disabled');
    const panel = journal.getByRole('region', { name: 'Aperçu de la notification client', exact: true });
    await expect(panel).toContainText(request.call_number || request.reference);
    await expect(panel).toContainText(request.client_reference);
    await expect(panel).toContainText(equipment.serial_number);
    await expect(panel).toContainText(entry.recipient_redacted);
    await expect(panel).not.toContainText(email);
    await expect(panel).not.toContainText(phone);
    await expect(panel).not.toContainText(company.notes);
    await expect(panel).not.toContainText(request.description);
    const retried = page.waitForResponse(result => new URL(result.url()).pathname === `/api/logistics/outbox/${entry.id}/retry/` && result.request().method() === 'POST');
    await panel.getByRole('button', { name: 'Confirmer la demande de relance', exact: true }).click();
    const retryResponse = await retried;
    expect(retryResponse.ok(), await retryResponse.text()).toBe(true);
    expect(retryResponse.request().postDataJSON().preview_token).toBe(preview.preview_token);
    expect(await retryResponse.json()).toMatchObject({ id: entry.id, state: 'blocked', blocked_reason: 'channel_disabled', attempts: 0, sent_at: null });
    await expect(journal.getByRole('region', { name: 'Aperçu de la notification client', exact: true })).toHaveCount(0);
    await expect(journal.getByRole('status')).toContainText('Demande de relance enregistrée. État actuel : Bloquée.');
    await expect(journal.locator('tbody tr')).toHaveCount(1);
    await expect(journal.locator('tbody tr')).toContainText('0 tentative(s)');
    await expect(journal).not.toContainText('Acceptée le ');
  }
  const final = await api(page, query);
  expect(final.results).toHaveLength(2);
  expect(final.counts).toMatchObject({ blocked: 2, sent: 0, pending: 0, processing: 0 });
  for (const entry of final.results) expect(entry).toMatchObject({ state: 'blocked', blocked_reason: 'channel_disabled', attempts: 0, sent_at: null });

  const portal = await api(page, 'users/', 'POST', { username: `portail-journal-${tag}`, role: 'client', client: company.id, password });
  const external = await api(page, 'users/', 'POST', { username: `externe-journal-${tag}`, role: 'courier', courier_kind: 'client', client: company.id, password });
  for (const [account, courier] of [[portal, false], [external, true]]) {
    const context = await browser.newContext();
    const outsider = await context.newPage();
    try {
      await login(outsider, account.username, courier);
      expect((await response(outsider, query)).status()).toBe(403);
      expect((await response(outsider, `logistics/outbox/${initial.results[0].id}/preview/`)).status()).toBe(403);
      await expect(outsider.getByRole('region', { name: 'Journal des notifications client', exact: true })).toHaveCount(0);
    } finally {
      await context.close();
    }
  }
});
