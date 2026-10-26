import { test, expect } from '@playwright/test';

const password = process.env.TVM_DEMO_PASSWORD;
async function login(page, username = 'admin') {
  if (!password) throw new Error('Utiliser bash scripts/e2e.sh.');
  await page.goto('/');
  await page.getByLabel('Identifiant', { exact: true }).fill(username);
  await page.getByLabel('Mot de passe', { exact: true }).fill(password);
  const loaded = page.waitForResponse(r => r.url().endsWith('/api/dashboard/') && r.ok());
  await page.getByRole('button', { name: /Se connecter/i }).click();
  await loaded;
  await expect(page.locator('.metric-value').first()).toContainText(/\d/);
}
async function response(page, path, method = 'GET', data) {
  const { csrfToken } = await (await page.request.get('/api/session/')).json();
  return page.request.fetch(`/api/${path}`, { method, data, headers: { 'X-CSRFToken': csrfToken } });
}
async function api(page, path, method = 'GET', data) {
  const result = await response(page, path, method, data);
  expect(result.ok(), `${method} ${path}: ${result.status()} ${await result.text()}`).toBeTruthy();
  return result.json();
}
async function reload(page) {
  const loaded = page.waitForResponse(r => r.url().endsWith('/api/dashboard/') && r.ok());
  await page.reload();
  await loaded;
  await expect(page.locator('.metric-value').first()).toContainText(/\d/);
}
async function navigate(page, text) {
  const nav = page.getByRole('navigation', { name: 'Navigation principale' });
  if (!await nav.isVisible()) await page.getByRole('button', { name: 'Ouvrir le menu', exact: true }).click();
  await nav.getByText(text, { exact: true }).click();
}
async function findRequest(page, marker, reference) {
  await navigate(page, 'Demandes SAV');
  await page.getByLabel('Rechercher une demande', { exact: true }).fill(marker);
  await page.locator('.request-workspace-toolbar').getByRole('button', { name: 'Rechercher', exact: true }).click();
  await page.getByRole('button', { name: `Ouvrir ${reference}`, exact: true }).click();
  return page.getByRole('dialog', { name: 'Dossier SAV', exact: true });
}
const weekAgo = () => new Date(Date.now() - 7 * 86400_000).toISOString();

test('la réception enregistre la vraie arrivée et les informations de suivi dans le parcours série existant', async ({ page }) => {
  await login(page);
  const marker = `Reception-${Date.now()}`;
  const client = await api(page, 'clients/', 'POST', { name: marker });
  const equipment = await api(page, 'equipment/', 'POST', { client: client.id, serial_number: marker, model: 'Onduleur de réception fictif' });
  await reload(page);
  await navigate(page, 'Demandes SAV');
  await page.getByRole('button', { name: 'Nouvelle demande', exact: true }).click();
  let dialog = page.getByRole('dialog');
  await dialog.getByRole('combobox', { name: /^Équipement concerné/ }).selectOption(String(equipment.id));
  await dialog.getByRole('textbox', { name: /^Objet du signalement/ }).fill(marker);
  await dialog.getByRole('textbox', { name: /^Description de la panne/ }).fill('Dossier fictif pour valider les champs de réception.');
  const arrived = weekAgo().slice(0, 16);
  await dialog.getByLabel('Date d’arrivée', { exact: true }).fill(arrived);
  await dialog.getByLabel('N° d’appel client / référence client', { exact: true }).fill(`REF-${marker}`);
  await dialog.getByLabel('Client final', { exact: true }).fill('Site final fictif');
  await dialog.getByLabel('Retour de matériel', { exact: true }).check();
  await dialog.getByLabel('Emballage reçu', { exact: true }).fill('Carton avec protections');
  await dialog.getByLabel('Lieu de prise en charge', { exact: true }).selectOption('workshop');
  await dialog.getByLabel('Matériel livré par', { exact: true }).selectOption('courier');
  await dialog.getByLabel('Nom du livreur', { exact: true }).fill('Livreur fictif');
  await dialog.getByLabel('Accessoires reçus', { exact: true }).fill('Câble et adaptateur de validation');
  await dialog.getByLabel('Situation de garantie du dossier', { exact: true }).selectOption('quotation');
  await dialog.getByLabel('Nom du contact', { exact: true }).fill('Contact de réception');
  await dialog.getByLabel('E-mail du contact', { exact: true }).fill('reception@example.invalid');
  await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  const rows = await api(page, `requests/?q=${encodeURIComponent(marker)}`);
  expect(rows).toHaveLength(1);
  const saved = rows[0];
  expect(saved).toMatchObject({ equipment: equipment.id, client_reference: `REF-${marker}`, return_flag: true, service_location: 'workshop', delivered_by: 'courier', warranty_status: 'quotation' });
  expect(saved.arrived_at).not.toBe(saved.created_at);
  expect(saved.timing).toMatchObject({ timer_state: 'running', clock_basis: 'business_hours_excluding_weekends', is_overdue_48h: true });
  const row = page.locator('.request-workspace tbody tr').filter({ hasText: saved.reference });
  await expect(row.locator('.request-timer-overdue')).toContainText('2 jours ouvrés dépassé');
  dialog = await findRequest(page, marker, saved.reference);
  await expect(dialog.getByRole('tab', { name: 'Suivi', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(dialog.getByRole('tabpanel')).toContainText(`REF-${marker}`);
  await expect(dialog.getByRole('tabpanel')).toContainText('Câble et adaptateur de validation');
  const pdf = await page.request.get(`/api/requests/${saved.id}/report/`);
  expect(pdf.status()).toBe(200);
  expect(pdf.headers()['cache-control']).toContain('no-store');
  expect((await pdf.body()).subarray(0, 5).toString()).toBe('%PDF-');
  await page.screenshot({ path: '../../.local/arrival-followup-desktop.png', fullPage: true });
});

test('le compteur distingue arrivée inconnue, délai respecté et clôture figée puis réouverture', async ({ page }) => {
  await login(page);
  const marker = `Compteur-${Date.now()}`;
  const client = (await api(page, 'clients/'))[0];
  const equipment = await api(page, 'equipment/', 'POST', { client: client.id, serial_number: marker, model: 'Onduleur de validation temps' });
  const unknown = await api(page, 'requests/', 'POST', { equipment: equipment.id, subject: `${marker}-sans-arrivee` });
  const recent = await api(page, 'requests/', 'POST', { equipment: equipment.id, subject: `${marker}-recent`, arrived_at: new Date(Date.now() - 60_000).toISOString() });
  const old = await api(page, 'requests/', 'POST', { equipment: equipment.id, subject: `${marker}-ancien`, arrived_at: weekAgo() });
  expect(unknown.timing.timer_state).toBe('unknown');
  expect(recent.timing.is_overdue_48h).toBe(false);
  expect(old.is_overdue).toBe(true);
  const closed = await api(page, `requests/${old.id}/`, 'PATCH', { status: 'closed' });
  expect(closed.closed_at).toBeTruthy();
  expect(closed.timing).toMatchObject({ timer_state: 'closed', is_overdue_48h: true });
  expect(closed.is_overdue).toBe(false);
  await api(page, `requests/${old.id}/timeline/`, 'POST', { kind: 'observation', observation: 'Note après clôture', is_internal: true });
  const again = await api(page, `requests/${old.id}/`);
  expect(again.closed_at).toBe(closed.closed_at);
  expect(again.timing.elapsed_hours).toBe(closed.timing.elapsed_hours);
  await reload(page);
  await navigate(page, 'Demandes SAV');
  await page.getByLabel('Rechercher une demande', { exact: true }).fill(marker);
  await page.locator('.request-workspace-toolbar').getByRole('button', { name: 'Rechercher', exact: true }).click();
  await expect(page.locator('tr').filter({ hasText: unknown.reference }).locator('.request-timer-unknown')).toBeVisible();
  await expect(page.locator('tr').filter({ hasText: recent.reference }).locator('.request-timer-on-time')).toBeVisible();
  await expect(page.locator('tr').filter({ hasText: old.reference }).locator('.request-timer-overdue')).toContainText('Durée figée à la clôture');
  const reopened = await api(page, `requests/${old.id}/`, 'PATCH', { status: 'pending' });
  expect(reopened.closed_at).toBeNull();
  expect(reopened.timing.timer_state).toBe('running');
  expect(reopened.is_overdue).toBe(true);
});

test('les documents privés et partagés sont téléversés, retrouvés depuis un autre compte et protégés par dossier', async ({ page, browser }) => {
  await login(page);
  const customerContext = await browser.newContext();
  const customer = await customerContext.newPage();
  try {
    await login(customer, 'client');
    const session = await (await customer.request.get('/api/session/')).json();
    const marker = `Documents-${Date.now()}`;
    const equipment = await api(page, 'equipment/', 'POST', { client: session.user.client, serial_number: marker, model: 'Matériel documentaire fictif' });
    const request = await api(page, 'requests/', 'POST', { equipment: equipment.id, subject: marker, arrived_at: weekAgo() });
    const generatedPdf = await page.request.get(`/api/requests/${request.id}/report/`);
    expect(generatedPdf.status()).toBe(200);
    const pdfBytes = await generatedPdf.body();
    await reload(page);
    const dialog = await findRequest(page, marker, request.reference);
    await dialog.getByRole('tab', { name: 'Documents', exact: true }).click();
    const documents = dialog.getByRole('region', { name: 'Documents du dossier SAV', exact: true });
    await documents.getByRole('button', { name: 'Ajouter un document', exact: true }).click();
    await expect(documents.getByRole('checkbox', { name: 'Partager ce document avec le client du dossier', exact: true })).not.toBeChecked();
    await documents.getByLabel('Fichier', { exact: true }).setInputFiles({ name: `${marker}-interne.pdf`, mimeType: 'application/pdf', buffer: pdfBytes });
    await documents.getByLabel('Libellé (facultatif)', { exact: true }).fill('Fiche réservée au SAV');
    await documents.getByRole('button', { name: 'Enregistrer le fichier', exact: true }).click();
    await expect(documents.getByRole('link', { name: `Télécharger ${marker}-interne.pdf`, exact: true })).toBeVisible();
    const first = await api(page, `requests/${request.id}/documents/`);
    expect(first.results).toHaveLength(1);
    const internal = first.results[0];
    expect(internal.client_visible).toBe(false);
    expect((await customer.request.get(`/api/documents/${internal.id}/download/`)).status()).toBe(404);
    expect((await api(customer, `requests/${request.id}/documents/`)).results).toEqual([]);
    // Uploading a second file is an explicit sharing decision, never a side effect of the first upload.
    if (!await documents.getByLabel('Fichier', { exact: true }).isVisible()) await documents.getByRole('button', { name: 'Ajouter un document', exact: true }).click();
    await documents.getByLabel('Fichier', { exact: true }).setInputFiles({ name: `${marker}-partage.txt`, mimeType: 'text/plain', buffer: Buffer.from('Document fictif destiné au client.\n') });
    await documents.getByRole('checkbox', { name: 'Partager ce document avec le client du dossier', exact: true }).check();
    await documents.getByRole('button', { name: 'Enregistrer le fichier', exact: true }).click();
    await expect(documents.getByRole('link', { name: `Télécharger ${marker}-partage.txt`, exact: true })).toBeVisible();
    const shared = (await api(customer, `requests/${request.id}/documents/`)).results;
    expect(shared).toHaveLength(1);
    expect(shared[0].client_visible).toBe(true);
    const download = await customer.request.get(`/api/documents/${shared[0].id}/download/`);
    expect(download.status()).toBe(200);
    expect(download.headers()['content-disposition']).toContain('attachment');
    expect(download.headers()['cache-control']).toContain('no-store');
    expect(await download.text()).toBe('Document fictif destiné au client.\n');
    expect((await response(customer, `documents/${shared[0].id}/`, 'DELETE')).status()).toBe(403);
    const otherClient = (await api(page, 'clients/')).find(row => row.id !== session.user.client);
    const otherEquipment = await api(page, 'equipment/', 'POST', { client: otherClient.id, serial_number: `${marker}-AUTRE`, model: 'Autre matériel fictif' });
    const foreign = await api(page, 'requests/', 'POST', { equipment: otherEquipment.id, subject: `${marker}-autre` });
    expect((await customer.request.get(`/api/requests/${foreign.id}/documents/`)).status()).toBe(404);
    expect((await customer.request.get(`/api/requests/${foreign.id}/report/`)).status()).toBe(404);
    await documents.getByRole('button', { name: `Supprimer ${marker}-interne.pdf`, exact: true }).click();
    await documents.getByRole('button', { name: 'Confirmer la suppression', exact: true }).click();
    await expect(documents.getByRole('link', { name: `Télécharger ${marker}-interne.pdf`, exact: true })).toHaveCount(0);
    expect((await page.request.get(`/api/documents/${internal.id}/download/`)).status()).toBe(404);
    // Exercise the UI presentation of a deferred physical cleanup. The server's
    // actual disk/DB failure cases are verified separately by PostgreSQL tests.
    const deferredMessage = 'Le document a été retiré. La suppression physique est en attente de reprise.';
    const deferredPath = `**/api/documents/${shared[0].id}/`;
    await page.route(deferredPath, async route => {
      const actual = await route.fetch();
      expect(actual.status()).toBe(204);
      await route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ detail: deferredMessage }) });
    });
    await documents.getByRole('button', { name: `Supprimer ${marker}-partage.txt`, exact: true }).click();
    await documents.getByRole('button', { name: 'Confirmer la suppression', exact: true }).click();
    await expect(documents.locator('.request-documents-success')).toHaveText(deferredMessage);
    await expect(documents.getByRole('link', { name: `Télécharger ${marker}-partage.txt`, exact: true })).toHaveCount(0);
    await page.unroute(deferredPath);
  } finally {
    await customerContext.close();
  }
});
