import { test, expect } from '@playwright/test';

const password = process.env.TVM_DEMO_PASSWORD;
test.beforeAll(() => {
  if (!password) throw new Error('TVM_DEMO_PASSWORD requis ; utiliser bash scripts/e2e.sh.');
});

async function login(page, username = 'admin', waitForData = true) {
  await page.goto('/');
  await page.getByLabel('Identifiant', { exact: true }).fill(username);
  await page.getByLabel('Mot de passe', { exact: true }).fill(password);
  const loaded = waitForData ? page.waitForResponse(response => response.url().endsWith('/api/dashboard/') && response.status() === 200) : null;
  await page.getByRole('button', { name: /Se connecter/i }).click();
  await expect(page.getByRole('heading', { name: /Tableau de bord|Mon espace/i }).first()).toBeVisible();
  if (loaded) {
    await loaded;
    await expect(page.locator('.metric-value').first()).toContainText(/\d/);
  }
}

async function api(page, path, method = 'GET', data) {
  const session = await page.request.get('/api/session/');
  const { csrfToken } = await session.json();
  const response = await page.request.fetch(`/api/${path}`, {
    method, data, headers: { 'X-CSRFToken': csrfToken },
  });
  expect(response.ok(), `${method} ${path} → ${response.status()}: ${await response.text()}`).toBeTruthy();
  return response.headers()['content-type']?.includes('application/json') ? response.json() : response.body();
}

test('les formulaires réalisent le parcours SAV complet', async ({ page }) => {
  await login(page);
  const marker = `Formulaire-${Date.now()}`;
  const navigate = async label => {
    await page.getByRole('navigation', { name: 'Navigation principale' }).getByText(label, { exact: true }).click();
  };
  const save = async () => {
    await page.getByRole('dialog').getByRole('button', { name: 'Enregistrer', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
  };
  await navigate('Clients');
  await page.getByRole('button', { name: 'Nouveau client', exact: true }).first().click();
  await page.getByLabel(/Raison sociale/).fill(marker);
  await page.getByLabel('Contact principal', { exact: true }).fill('Contact de validation');
  await save();
  await expect(page.getByRole('cell', { name: new RegExp(marker) }).first()).toBeVisible();
  await navigate('Équipements');
  await page.getByRole('button', { name: 'Nouvel équipement', exact: true }).first().click();
  await page.getByRole('dialog').getByLabel(/^Client/).selectOption({ label: marker });
  await page.getByLabel(/Numéro de série/).fill(marker);
  await page.getByLabel(/^Modèle/).fill('93PM');
  await page.getByLabel('Puissance (kVA)', { exact: true }).fill('100');
  await save();
  await navigate('Demandes SAV');
  await page.getByRole('button', { name: 'Nouvelle demande', exact: true }).first().click();
  const equipmentSelect = page.getByLabel(/Équipement concerné/);
  const equipmentValue = await equipmentSelect.getByRole('option').filter({ hasText: marker }).getAttribute('value');
  await equipmentSelect.selectOption(equipmentValue);
  await page.getByLabel(/Objet du signalement/).fill(marker);
  await page.getByLabel(/Description de la panne/).fill('Alarme batterie à traiter sur site.');
  await save();
  await navigate('Interventions');
  await page.getByRole('button', { name: 'Nouvelle intervention', exact: true }).first().click();
  const requestSelect = page.getByLabel(/^Demande SAV/);
  const requestValue = await requestSelect.getByRole('option').filter({ hasText: marker }).getAttribute('value');
  await requestSelect.selectOption(requestValue);
  await page.getByLabel('Diagnostic et observations', { exact: true }).fill('Batterie défectueuse détectée.');
  await page.getByLabel('Travaux réalisés', { exact: true }).fill('Batterie remplacée et test fonctionnel réussi.');
  await page.getByRole('dialog').getByRole('combobox', { name: 'Statut', exact: true }).selectOption('completed');
  await save();
  const interventions = await api(page, 'interventions/');
  const result = interventions.find(item => item.equipment_serial === marker);
  expect(result.status).toBe('completed');
  await page.getByRole('button', { name: `Voir ${result.reference}`, exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('Batterie remplacée');
  const pdf = await page.request.get(`/api/interventions/${result.id}/report/`);
  expect(pdf.status()).toBe(200);
  expect((await pdf.body()).subarray(0, 5).toString()).toBe('%PDF-');
});

test('parcours persistant client → onduleur → demande → intervention → PDF', async ({ page, browser }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await login(page);
  const marker = `E2E-${Date.now()}`;
  const client = await api(page, 'clients/', 'POST', { name: marker, email: 'contact@example.invalid', city: 'Lyon' });
  const equipment = await api(page, 'equipment/', 'POST', { client: client.id, serial_number: marker, model: '93PM', brand: 'Eaton', power_kva: '100.00', location: 'Salle serveur' });
  const request = await api(page, 'requests/', 'POST', { equipment: equipment.id, subject: 'Alarme batterie', description: 'Validation navigateur du parcours SAV.', priority: 'high' });
  const users = await api(page, 'users/');
  const tech = users.find(user => user.username === 'technicien');
  const intervention = await api(page, 'interventions/', 'POST', { service_request: request.id, technician: tech.id, scheduled_at: new Date().toISOString(), diagnosis: 'Batterie à remplacer', internal_notes: 'CONFIDENTIEL-E2E' });
  await api(page, `interventions/${intervention.id}/`, 'PATCH', { status: 'completed', work_done: 'Remplacement de la batterie et test de charge.', recommendations: 'Vérification dans six mois.' });
  const pdf = await api(page, `interventions/${intervention.id}/report/`);
  expect(pdf.subarray(0, 5).toString()).toBe('%PDF-');
  expect(pdf.length).toBeGreaterThan(1500);

  // A separate browser session proves that the data lives on the server.
  const second = await browser.newContext();
  const other = await second.newPage();
  await login(other, 'responsable');
  const recovered = await api(other, `equipment/${equipment.id}/`);
  expect(recovered.serial_number).toBe(marker);
  const recoveredIntervention = await api(other, `interventions/${intervention.id}/`);
  expect(recoveredIntervention.status).toBe('completed');
  await second.close();
  await page.screenshot({ path: '../../.local/powercare-dashboard-desktop.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('le portail client filtre les listes, recherche et PDF côté serveur', async ({ page, browser }) => {
  await login(page, 'client');
  const session = await (await page.request.get('/api/session/')).json();
  const myClient = session.user.client;
  const clients = await api(page, 'clients/');
  expect(clients.length).toBe(1);
  expect(clients[0].id).toBe(myClient);
  const equipment = await api(page, 'equipment/');
  expect(equipment.length).toBeGreaterThan(0);
  expect(equipment.every(item => item.client === myClient)).toBeTruthy();
  const interventions = await api(page, 'interventions/');
  expect(interventions.every(item => !Object.hasOwn(item, 'internal_notes'))).toBeTruthy();

  const adminContext = await browser.newContext();
  const admin = await adminContext.newPage();
  await login(admin);
  const allEquipment = await api(admin, 'equipment/');
  const foreign = allEquipment.find(item => item.client !== myClient);
  expect(foreign).toBeTruthy();
  expect((await page.request.get(`/api/equipment/${foreign.id}/`)).status()).toBe(404);
  const search = await api(page, `search/?q=${encodeURIComponent(foreign.serial_number)}`);
  expect(search.equipment).toEqual([]);
  const allInterventions = await api(admin, 'interventions/');
  const foreignIntervention = allInterventions.find(item => item.equipment_serial === foreign.serial_number);
  if (foreignIntervention) expect((await page.request.get(`/api/interventions/${foreignIntervention.id}/report/`)).status()).toBe(404);
  expect((await page.request.get('/api/parts/')).status()).toBe(403);
  expect((await page.request.get('/api/users/')).status()).toBe(403);
  await adminContext.close();
});

test('la navigation reste utilisable sur téléphone', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page, 'technicien');
  await expect(page.getByRole('heading').first()).toBeVisible();
  const overflows = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2);
  expect(overflows).toBeFalsy();
  await page.screenshot({ path: '../../.local/powercare-mobile.png', fullPage: true });
});

test('un changement de compte ignore les anciennes réponses et efface les données privées', async ({ page }) => {
  let delayed = false;
  let release;
  let finished;
  const gate = new Promise(resolve => { release = resolve; });
  const completed = new Promise(resolve => { finished = resolve; });
  await page.route('**/api/equipment/', async route => {
    const response = await route.fetch();
    if (!delayed) {
      delayed = true;
      await gate;
      await route.fulfill({ response });
      finished();
    } else {
      await route.fulfill({ response });
    }
  });
  await login(page, 'admin', false);
  await expect.poll(() => delayed).toBeTruthy();
  await page.getByRole('button', { name: 'Se déconnecter', exact: true }).click();
  await page.getByLabel('Identifiant', { exact: true }).fill('client');
  await page.getByLabel('Mot de passe', { exact: true }).fill(password);
  const loaded = page.waitForResponse(response => response.url().endsWith('/api/dashboard/') && response.status() === 200);
  await page.getByRole('button', { name: /Se connecter/i }).click();
  await loaded;
  const ownEquipment = await api(page, 'equipment/');
  release();
  await completed;
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.getByRole('navigation').getByText('Équipements', { exact: true }).click();
  await expect(page.locator('tbody tr')).toHaveCount(ownEquipment.length);
  for (const equipment of ownEquipment) await expect(page.getByRole('cell', { name: new RegExp(equipment.serial_number) }).first()).toBeVisible();
  await expect(page.getByRole('navigation')).not.toContainText('Comptes & accès');
});
