import { test, expect } from '@playwright/test';

const password = process.env.TVM_DEMO_PASSWORD;

async function login(page, username = 'admin') {
  if (!password) throw new Error('TVM_DEMO_PASSWORD requis ; utiliser bash scripts/e2e.sh.');
  await page.goto('/');
  await page.getByLabel('Identifiant', { exact: true }).fill(username);
  await page.getByLabel('Mot de passe', { exact: true }).fill(password);
  const loaded = page.waitForResponse(result => result.url().endsWith('/api/dashboard/') && result.ok());
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
  expect(result.ok(), `${method} ${path} → ${result.status()}: ${await result.text()}`).toBeTruthy();
  return result.json();
}

async function importCsv(page, file, mode, sha256) {
  const { csrfToken } = await (await page.request.get('/api/session/')).json();
  return page.request.post('/api/clients/import/', {
    headers: { 'X-CSRFToken': csrfToken },
    multipart: { file, mode, ...(sha256 ? { sha256 } : {}) },
  });
}

async function reload(page) {
  const loaded = page.waitForResponse(result => result.url().endsWith('/api/dashboard/') && result.ok());
  await page.reload();
  await loaded;
}

async function navigate(page, label) {
  const navigation = page.getByRole('navigation', { name: 'Navigation principale' });
  if (!await navigation.isVisible()) await page.getByRole('button', { name: 'Ouvrir le menu', exact: true }).click();
  await navigation.getByText(label, { exact: true }).click();
}

async function openRequest(page, record) {
  await navigate(page, 'Demandes SAV');
  await page.getByRole('group', { name: 'Catégories des demandes SAV', exact: true }).getByRole('button', { name: /^Tous/ }).click();
  await page.getByLabel('Rechercher une demande', { exact: true }).fill(record.call_number || record.reference);
  await page.locator('.request-workspace-toolbar').getByRole('button', { name: 'Rechercher', exact: true }).click();
  await page.getByRole('button', { name: `Ouvrir ${record.reference}`, exact: true }).click();
  return page.getByRole('dialog', { name: 'Dossier SAV', exact: true });
}

function marker(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

const csvColumns = ['name', 'contact_name', 'tax_id', 'email', 'phone', 'address', 'city', 'postal_code', 'country', 'notes'];
function csvCell(value) {
  const text = String(value ?? '');
  return /[;"\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}
function clientFile(records) {
  const text = '\ufeff' + [csvColumns.join(';'), ...records.map(record => csvColumns.map(key => csvCell(record[key])).join(';'))].join('\r\n') + '\r\n';
  return { name: 'clients-fictifs.csv', mimeType: 'text/csv', buffer: Buffer.from(text, 'utf8') };
}

test('l’annuaire retrouve les coordonnées fiscales et les compteurs réels sans exposer les notes internes au portail', async ({ page, browser }) => {
  test.setTimeout(180000);
  await login(page);
  const tag = marker('Annuaire-fictif');
  const company = await api(page, 'clients/', 'POST', {
    name: `Laboratoire Énergie ${tag}`, contact_name: 'Contact fictif annuaire',
    tax_id: `000-42-${tag}`, email: `annuaire-${Date.now()}@example.invalid`,
    phone: '0000123400', address: 'Adresse de test uniquement', city: 'Cotonou',
    postal_code: '00001', country: 'Bénin', notes: `NOTE-INTERNE-${tag}`,
  });
  const foreign = await api(page, 'clients/', 'POST', { name: `Autre société ${tag}`, tax_id: `AUTRE-${tag}`, notes: `NOTE-AUTRE-${tag}` });
  const equipment = await api(page, 'equipment/', 'POST', { client: company.id, serial_number: `${tag}-A`, model: 'Onduleur fictif annuaire' });
  await api(page, 'equipment/', 'POST', { client: company.id, serial_number: `${tag}-B`, model: 'Second onduleur fictif' });
  await api(page, 'requests/', 'POST', { equipment: equipment.id, subject: `Ouvert ${tag}`, status: 'pending' });
  await api(page, 'requests/', 'POST', { equipment: equipment.id, subject: `Clos ${tag}`, status: 'closed' });
  const username = `annuaire-client-${Date.now()}`;
  await api(page, 'users/', 'POST', { username, role: 'client', client: company.id, password });
  const stored = await api(page, `clients/${company.id}/`);
  expect(stored).toMatchObject({ tax_id: company.tax_id, phone: '0000123400', equipment_count: 2, open_requests_count: 1, portal_users_count: 1 });

  await reload(page);
  await navigate(page, 'Clients');
  const search = page.getByLabel('Rechercher un client', { exact: true });
  const searched = page.waitForResponse(result => {
    const url = new URL(result.url());
    return url.pathname === '/api/clients/' && url.searchParams.get('q') === company.tax_id && result.ok();
  });
  await search.fill(company.tax_id);
  await searched;
  const rows = page.locator('.client-directory-table tbody tr');
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText(company.name);
  await expect(rows.first()).toContainText(company.tax_id);
  await expect(rows.first()).toContainText('0000123400');
  await expect(rows.first()).toContainText('2 équipements');
  await expect(rows.first()).toContainText('1 dossier ouvert');
  await page.getByRole('button', { name: `Consulter ${company.name}`, exact: true }).click();
  const profile = page.getByRole('dialog', { name: 'Fiche client', exact: true });
  await expect(profile).toContainText(company.tax_id);
  await expect(profile).toContainText(`NOTE-INTERNE-${tag}`);
  await expect(profile).toContainText('1 compte(s) associé(s)');
  await profile.getByRole('button', { name: 'Gérer les comptes et accès', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Comptes & accès', exact: true })).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Rechercher dans comptes & accès', exact: true })).toHaveValue(company.name);
  const associatedAccounts = page.locator('.resource-card tbody tr');
  await expect(associatedAccounts).toHaveCount(1);
  await expect(associatedAccounts.first()).toContainText(username);

  const clientContext = await browser.newContext();
  const customer = await clientContext.newPage();
  try {
    await login(customer, username);
    const own = await api(customer, 'clients/');
    expect(own.map(client => client.id)).toEqual([company.id]);
    expect(own[0].tax_id).toBe(company.tax_id);
    expect(Object.hasOwn(own[0], 'notes')).toBe(false);
    expect(Object.hasOwn(own[0], 'portal_users_count')).toBe(false);
    expect(await api(customer, `clients/?q=${encodeURIComponent(foreign.tax_id)}`)).toEqual([]);
    expect((await response(customer, `clients/${foreign.id}/`)).status()).toBe(404);
    expect((await response(customer, `clients/${company.id}/`, 'PATCH', { tax_id: 'FORGÉ' })).status()).toBe(403);
    const forbidden = await importCsv(customer, clientFile([{ name: `Interdit ${tag}` }]), 'preview');
    expect(forbidden.status()).toBe(403);
    await expect(customer.locator('main')).not.toContainText(`NOTE-INTERNE-${tag}`);
    await expect(customer.getByRole('button', { name: 'Importer des clients', exact: true })).toHaveCount(0);
  } finally {
    await clientContext.close();
  }
});

test('l’import CSV se prévisualise sans écriture puis crée les nouveaux clients valides sans fusion ni compte portail', async ({ page }) => {
  test.setTimeout(180000);
  await login(page);
  const tag = marker('CSV-fictif');
  const base = {
    contact_name: 'Contact fictif CSV', phone: '0000001234', address: 'Adresse fictive CSV',
    city: 'Porto-Novo', postal_code: '00002', country: 'Bénin', notes: `Note interne initiale ${tag}`,
  };
  const existing = await api(page, 'clients/', 'POST', { ...base, name: `Déjà présent ${tag}`, tax_id: `EXISTANT-${tag}`, email: `existing-${Date.now()}@example.invalid` });
  const conflict = await api(page, 'clients/', 'POST', { ...base, name: `À conserver ${tag}`, tax_id: `CONFLIT-${tag}`, email: `conflict-${Date.now()}@example.invalid` });
  const first = { ...base, name: `Énergie ; laboratoire ${tag}`, tax_id: `000-A-${tag}`, email: `new-a-${Date.now()}@example.invalid`, notes: `Note fictive accentuée\nSeconde ligne ${tag}` };
  const second = { ...base, name: `Nouvelle société ${tag}`, tax_id: `000-B-${tag}`, email: `new-b-${Date.now()}@example.invalid` };
  const invalid = { ...base, name: `Ligne invalide ${tag}`, tax_id: `INVALIDE-${tag}`, email: 'ceci-n-est-pas-un-email' };
  const file = clientFile([first, second, first, existing, { ...conflict, notes: `NE-PAS-ÉCRASER-${tag}` }, invalid]);
  const userIdsBefore = (await api(page, 'users/')).map(user => user.id).sort((a, b) => a - b);
  const originalIds = (await api(page, `clients/?q=${encodeURIComponent(tag)}`)).map(client => client.id).sort((a, b) => a - b);

  await reload(page);
  await navigate(page, 'Clients');
  await page.getByRole('button', { name: 'Importer des clients', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Importer des clients', exact: true });
  await dialog.getByLabel('Fichier clients CSV', { exact: true }).setInputFiles(file);
  const previewResponse = page.waitForResponse(result => result.url().endsWith('/api/clients/import/') && result.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Prévisualiser l’import', exact: true }).click();
  const previewResult = await previewResponse;
  expect(previewResult.status(), await previewResult.text()).toBe(200);
  const preview = await previewResult.json();
  expect(preview).toMatchObject({ applied: false, mode: 'preview', summary: { total: 6, create: 2, existing: 1, duplicate: 1, conflict: 1, invalid: 1, created: 0 } });
  expect(preview.sha256).toMatch(/^[a-f0-9]{64}$/);
  await expect(dialog.getByLabel('Aperçu de l’import clients')).toContainText(first.name);
  await expect(dialog).toContainText('L’aperçu n’a créé aucune société.');
  expect((await api(page, `clients/?q=${encodeURIComponent(tag)}`)).map(client => client.id).sort((a, b) => a - b)).toEqual(originalIds);
  expect((await api(page, 'users/')).map(user => user.id).sort((a, b) => a - b)).toEqual(userIdsBefore);

  const applyResponse = page.waitForResponse(result => result.url().endsWith('/api/clients/import/') && result.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Appliquer l’import', exact: true }).click();
  const applyResult = await applyResponse;
  expect(applyResult.status(), await applyResult.text()).toBe(200);
  const applied = await applyResult.json();
  expect(applied).toMatchObject({ applied: true, mode: 'apply', summary: { total: 6, created: 2, skipped: 4 } });
  await expect(dialog).toContainText('2 société(s) créée(s), 4 ligne(s) ignorée(s)');
  const after = await api(page, `clients/?q=${encodeURIComponent(tag)}`);
  expect(after).toHaveLength(4);
  const imported = after.find(client => client.name === first.name);
  expect(imported).toMatchObject({ tax_id: first.tax_id, phone: '0000001234', country: 'Bénin', notes: first.notes, equipment_count: 0, open_requests_count: 0, portal_users_count: 0 });
  expect(after.some(client => client.name === invalid.name)).toBe(false);
  expect((await api(page, `clients/${existing.id}/`)).notes).toBe(base.notes);
  expect((await api(page, `clients/${conflict.id}/`)).notes).toBe(base.notes);
  expect((await api(page, 'users/')).map(user => user.id).sort((a, b) => a - b)).toEqual(userIdsBefore);
  // Replaying the same source cannot create a second copy of the new clients.
  const repeatedResponse = await importCsv(page, file, 'apply', preview.sha256);
  expect(repeatedResponse.status(), await repeatedResponse.text()).toBe(200);
  expect((await repeatedResponse.json()).summary.created).toBe(0);
  expect((await api(page, `clients/?q=${encodeURIComponent(tag)}`))).toHaveLength(4);

  // Pasted source follows the same preview and cannot re-create these clients.
  const pasteMode = dialog.getByRole('button', { name: 'Coller un CSV', exact: true });
  await pasteMode.click();
  await expect(pasteMode).toHaveAttribute('aria-pressed', 'true');
  await dialog.getByLabel('Contenu CSV à coller', { exact: true }).fill(file.buffer.toString('utf8'));
  await expect(dialog.getByLabel('Aperçu de l’import clients')).toHaveCount(0);
  const pastedPreviewResponse = page.waitForResponse(result => result.url().endsWith('/api/clients/import/') && result.request().method() === 'POST');
  await dialog.getByRole('button', { name: 'Prévisualiser l’import', exact: true }).click();
  const pastedPreviewResult = await pastedPreviewResponse;
  expect(pastedPreviewResult.status(), await pastedPreviewResult.text()).toBe(200);
  expect(await pastedPreviewResult.json()).toMatchObject({ applied: false, mode: 'preview', summary: { total: 6, create: 0, created: 0 } });
  await expect(dialog.getByRole('button', { name: 'Appliquer l’import', exact: true })).toBeDisabled();
  expect((await api(page, `clients/?q=${encodeURIComponent(tag)}`))).toHaveLength(4);
  expect((await api(page, 'users/')).map(user => user.id).sort((a, b) => a - b)).toEqual(userIdsBefore);
});

test('une prévision de trois visites reste un objectif et seules les préventives réalisées du même appel font progresser la campagne', async ({ page, browser }) => {
  test.setTimeout(180000);
  await login(page);
  const tag = marker('Campagne-fictive');
  const company = await api(page, 'clients/', 'POST', { name: `Campagne ${tag}` });
  const equipment = await api(page, 'equipment/', 'POST', { client: company.id, serial_number: `${tag}-SERIE`, model: 'Onduleur fictif de campagne' });
  const campaign = await api(page, 'requests/', 'POST', { equipment: equipment.id, subject: `Préventive ${tag}`, status: 'pending' });
  expect(campaign.planned_visit_count).toBeNull();
  expect(campaign.preventive_remaining_visit_count).toBeNull();
  expect(campaign.preventive_completed_visit_count).toBe(0);
  expect(await api(page, `interventions/?call_number=${encodeURIComponent(campaign.reference)}`)).toEqual([]);
  await reload(page);
  let dossier = await openRequest(page, campaign);
  await dossier.getByRole('tab', { name: /^Préventive/ }).click();
  await expect(dossier.locator('.preventive-progress').first()).toContainText('Prévision non renseignée');
  await dossier.getByRole('button', { name: 'Modifier le dossier', exact: true }).click();
  let form = page.getByRole('dialog');
  await form.getByLabel('Nombre de visites préventives prévues', { exact: true }).fill('3');
  const targetSaved = page.waitForResponse(result => result.url().endsWith(`/api/requests/${campaign.id}/`) && result.request().method() === 'PATCH');
  await form.getByRole('button', { name: 'Enregistrer les modifications', exact: true }).click();
  const targetResponse = await targetSaved;
  expect(targetResponse.status(), await targetResponse.text()).toBe(200);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(await api(page, `interventions/?call_number=${encodeURIComponent(campaign.reference)}`)).toEqual([]);
  expect(await api(page, `requests/${campaign.id}/`)).toMatchObject({ planned_visit_count: 3, preventive_completed_visit_count: 0, preventive_total_visit_count: 0, preventive_remaining_visit_count: 3 });

  dossier = await openRequest(page, campaign);
  await dossier.getByRole('tab', { name: /^Préventive/ }).click();
  await expect(dossier.locator('.preventive-progress').first()).toContainText('0 / 3 visites réalisées');
  await dossier.getByRole('button', { name: 'Créer une fiche', exact: true }).click();
  form = page.getByRole('dialog');
  await expect(form.getByRole('combobox', { name: 'Type de fiche', exact: true })).toHaveValue('preventive');
  await expect(form.getByRole('combobox', { name: 'Demande SAV', exact: true })).toHaveValue(String(campaign.id));
  const { as_of: today } = await api(page, 'requests/categories/');
  await form.getByLabel('Date de l’opération', { exact: true }).fill(today);
  await form.getByLabel('Travaux réalisés', { exact: true }).fill(`Première visite réellement enregistrée ${tag}`);
  await form.getByLabel('Synthèse de l’opération', { exact: true }).fill(`Contrôle préventif fictif ${tag}`);
  await form.getByRole('combobox', { name: 'Statut', exact: true }).selectOption('completed');
  const visitSaved = page.waitForResponse(result => result.url().endsWith('/api/interventions/') && result.request().method() === 'POST');
  await form.getByRole('button', { name: 'Enregistrer', exact: true }).click();
  const visitResponse = await visitSaved;
  expect(visitResponse.status(), await visitResponse.text()).toBe(201);
  const performed = await visitResponse.json();
  await expect(page.getByRole('dialog')).toHaveCount(0);

  const scheduled = await api(page, 'interventions/', 'POST', { service_request: campaign.id, kind: 'preventive', status: 'scheduled' });
  await api(page, 'interventions/', 'POST', { service_request: campaign.id, kind: 'preventive', status: 'cancelled' });
  const commissioning = await api(page, 'interventions/', 'POST', { service_request: campaign.id, kind: 'commissioning', status: 'completed', performed_on: today, work_done: `Mise en service distincte ${tag}` });
  const secondRequest = await api(page, 'requests/', 'POST', { equipment: equipment.id, subject: `Autre appel ${tag}`, status: 'pending', planned_visit_count: 1 });
  await api(page, 'interventions/', 'POST', { service_request: secondRequest.id, kind: 'preventive', status: 'completed', performed_on: today, work_done: 'Visite appartenant à un autre appel du même onduleur.' });
  const progress = { planned_visit_count: 3, preventive_completed_visit_count: 1, preventive_total_visit_count: 2, preventive_remaining_visit_count: 2 };
  expect(await api(page, `requests/${campaign.id}/`)).toMatchObject(progress);
  expect(await api(page, `interventions/${performed.id}/`)).toMatchObject({ ...progress, call_number: campaign.reference });
  expect(await api(page, `requests/${secondRequest.id}/`)).toMatchObject({ planned_visit_count: 1, preventive_completed_visit_count: 1, preventive_remaining_visit_count: 0 });
  const forged = await response(page, `interventions/${scheduled.id}/`, 'PATCH', { planned_visit_count: 999, preventive_completed_visit_count: 999 });
  expect([200, 400]).toContain(forged.status());
  expect(await api(page, `requests/${campaign.id}/`)).toMatchObject(progress);

  await reload(page);
  dossier = await openRequest(page, campaign);
  await dossier.getByRole('tab', { name: /^Préventive/ }).click();
  await expect(dossier.locator('.preventive-progress').first()).toContainText('1 / 3 visites réalisées');
  await expect(dossier.locator('.preventive-progress').first()).toContainText('2 visites restantes');
  await expect(dossier.locator('.preventive-progress').first()).toContainText('2 fiches préventives enregistrées');
  await dossier.getByRole('button', { name: 'Fermer', exact: true }).first().click();
  await navigate(page, 'Préventive');
  await expect(page.getByRole('button', { name: `Voir ${performed.reference}`, exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: `Voir ${commissioning.reference}`, exact: true })).toHaveCount(0);
  await navigate(page, 'Mise en service');
  await expect(page.getByRole('button', { name: `Voir ${commissioning.reference}`, exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: `Voir ${performed.reference}`, exact: true })).toHaveCount(0);

  const clientUsername = `campagne-client-${Date.now()}`;
  await api(page, 'users/', 'POST', { username: clientUsername, role: 'client', client: company.id, password });
  const users = await api(page, 'users/');
  const technician = users.find(user => user.username === 'technicien');
  expect(technician).toBeTruthy();
  await api(page, `requests/${campaign.id}/`, 'PATCH', { assigned_technician: technician.id });
  const clientContext = await browser.newContext();
  const technicianContext = await browser.newContext();
  try {
    const customer = await clientContext.newPage();
    const worker = await technicianContext.newPage();
    await login(customer, clientUsername);
    await login(worker, 'technicien');
    expect(await api(customer, `requests/${campaign.id}/`)).toMatchObject(progress);
    expect((await response(customer, `requests/${campaign.id}/`, 'PATCH', { planned_visit_count: 4 })).status()).toBe(403);
    expect([400, 403]).toContain((await response(worker, `requests/${campaign.id}/`, 'PATCH', { planned_visit_count: 4 })).status());
    expect(await api(page, `requests/${campaign.id}/`)).toMatchObject(progress);
  } finally {
    await clientContext.close();
    await technicianContext.close();
  }
});
