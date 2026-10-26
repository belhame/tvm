import { test, expect } from '@playwright/test';

const password = process.env.TVM_DEMO_PASSWORD;

async function login(page, username = 'admin') {
  if (!password) throw new Error('TVM_DEMO_PASSWORD requis ; utiliser bash scripts/e2e.sh.');
  await page.goto('/');
  await page.getByLabel('Identifiant', { exact: true }).fill(username);
  await page.getByLabel('Mot de passe', { exact: true }).fill(password);
  const loaded = page.waitForResponse(response => response.url().endsWith('/api/dashboard/') && response.ok());
  await page.getByRole('button', { name: /Se connecter/i }).click();
  await loaded;
  await expect(page.locator('.metric-value').first()).toContainText(/\d/);
}

async function response(page, path, method = 'GET', data) {
  const session = await page.request.get('/api/session/');
  const { csrfToken } = await session.json();
  return page.request.fetch(`/api/${path}`, { method, data, headers: { 'X-CSRFToken': csrfToken } });
}

async function api(page, path, method = 'GET', data) {
  const result = await response(page, path, method, data);
  expect(result.ok(), `${method} ${path} → ${result.status()}: ${await result.text()}`).toBeTruthy();
  return result.json();
}

async function refresh(page) {
  const loaded = page.waitForResponse(result => result.url().endsWith('/api/dashboard/') && result.ok());
  await page.reload();
  await loaded;
  await expect(page.locator('.metric-value').first()).toContainText(/\d/);
}

async function navigate(page, label) {
  const navigation = page.getByRole('navigation', { name: 'Navigation principale' });
  if (!await navigation.isVisible()) await page.getByRole('button', { name: 'Ouvrir le menu', exact: true }).click();
  await navigation.getByText(label, { exact: true }).click();
}

test('les sous-catégories et la recherche retrouvent les états réels, y compris les anciens états et les retards', async ({ page }) => {
  await login(page);
  const marker = `Filtres-${Date.now()}`;
  const client = await api(page, 'clients/', 'POST', { name: marker });
  const equipment = await api(page, 'equipment/', 'POST', { client: client.id, serial_number: marker, model: 'Validation des catégories' });
  const calendar = await api(page, 'requests/categories/');
  const yesterday = new Date(`${calendar.as_of}T12:00:00Z`);
  yesterday.setUTCDate(yesterday.getUTCDate() - 1);
  const states = ['new', 'maintenance', 'testing', 'resolved', 'quotation', 'pending', 'approved', 'rejected', 'exchange', 'closed', 'scheduled', 'in_progress'];
  const records = [];
  for (const status of states) records.push(await api(page, 'requests/', 'POST', {
    equipment: equipment.id, subject: `${marker} ${status}`, status, due_on: yesterday.toISOString().slice(0, 10),
  }));
  const mapping = {
    unassigned: ['new'], maintenance: ['maintenance', 'in_progress'], testing: ['testing'],
    overdue: states.filter(status => !['resolved', 'rejected', 'closed'].includes(status)),
    processed: ['resolved'], quotation: ['quotation'], pending: ['pending', 'scheduled'],
    approved: ['approved'], rejected: ['rejected'], exchange: ['exchange'], closed: ['closed'], all: states,
  };
  const filteredCounts = await api(page, `requests/categories/?q=${marker}`);
  expect(filteredCounts.total).toBe(states.length);
  for (const category of filteredCounts.categories) expect(category.count, category.key).toBe(mapping[category.key].length);

  await refresh(page);
  await navigate(page, 'Demandes SAV');
  const tabs = page.getByRole('group', { name: 'Catégories des demandes SAV', exact: true });
  await page.getByLabel('Rechercher une demande', { exact: true }).fill(marker);
  await page.locator('.request-workspace-toolbar').getByRole('button', { name: 'Rechercher', exact: true }).click();
  const allCounts = await api(page, 'requests/categories/');
  for (const category of allCounts.categories) {
    const label = category.key === 'overdue' ? /^En dépassement(?: de)? délai$/ : new RegExp(`^${category.label}$`);
    const tab = tabs.getByRole('button').filter({ has: page.locator('span').filter({ hasText: label }) });
    await expect(tab).toHaveCount(1);
    await expect(tab.locator('.request-category-count')).toHaveText(String(category.count));
    await tab.click();
    await expect(tab).toHaveAttribute('aria-pressed', 'true');
    const expected = records.filter(record => mapping[category.key].includes(record.status)).map(record => record.reference).sort();
    await expect.poll(async () => (await page.locator('.request-workspace tbody tr .primary-cell > span').allTextContents()).sort(), {
      message: `La catégorie ${category.key} doit présenter uniquement les dossiers filtrés attendus`,
    }).toEqual(expected);
  }
});

test('les événements datés persistent et le portail exclut les observations internes et les autres clients', async ({ page, browser }) => {
  await login(page);
  const customerContext = await browser.newContext();
  const customer = await customerContext.newPage();
  const technicianContext = await browser.newContext();
  const technician = await technicianContext.newPage();
  try {
    await login(customer, 'client');
    const session = await (await customer.request.get('/api/session/')).json();
    const marker = `Chronologie-${Date.now()}`;
    const equipment = await api(page, 'equipment/', 'POST', {
      client: session.user.client, serial_number: marker, model: 'Onduleur de validation',
    });
    const users = await api(page, 'users/');
    const assigned = users.find(user => user.username === 'technicien');
    expect(assigned).toBeTruthy();
    const request = await api(page, 'requests/', 'POST', {
      equipment: equipment.id, subject: marker, status: 'pending', assigned_technician: assigned.id,
    });
    const privateNote = `${marker} observation réservée au SAV`;
    const publicSummary = `${marker} synthèse destinée au client`;
    const internal = await api(page, `equipment/${equipment.id}/timeline/`, 'POST', {
      kind: 'observation', observation: privateNote,
    });
    expect(internal.is_internal).toBe(true);
    const shared = await api(page, `requests/${request.id}/timeline/`, 'POST', {
      kind: 'summary', summary: publicSummary, is_internal: false,
    });
    expect(shared.is_internal).toBe(false);
    const privateTransitionNote = `${marker} précision interne de transition`;
    const transition = await api(page, `requests/${request.id}/timeline/`, 'POST', {
      kind: 'status_changed', status_after: 'testing', is_internal: true, observation: privateTransitionNote,
    });
    expect(transition).toMatchObject({ status_before: 'pending', status_after: 'testing' });
    expect((await api(page, `requests/${request.id}/`)).status).toBe('testing');
    expect((await response(page, `requests/${request.id}/timeline/`, 'POST', {
      kind: 'status_changed', status_after: 'new', is_internal: false,
    })).status()).toBe(400);
    expect((await api(page, `requests/${request.id}/`)).status).toBe('testing');
    const internalHistory = await api(page, `equipment/${equipment.id}/timeline/`);
    expect(internalHistory.some(event => event.id === internal.id && event.observation === privateNote)).toBe(true);
    expect(internalHistory.some(event => event.id === shared.id && event.summary === publicSummary)).toBe(true);
    expect(internalHistory.filter(event => event.kind === 'status_changed')).toHaveLength(1);
    for (const event of internalHistory) {
      expect(Number.isNaN(Date.parse(event.created_at))).toBe(false);
      expect(event.equipment).toBe(equipment.id);
    }

    const clientHistory = await api(customer, `equipment/${equipment.id}/timeline/`);
    expect(JSON.stringify(clientHistory)).not.toContain(privateNote);
    expect(JSON.stringify(clientHistory)).not.toContain(privateTransitionNote);
    expect(clientHistory.some(event => event.id === shared.id)).toBe(true);
    expect(clientHistory.every(event => event.is_internal === false && event.actor_name === 'Équipe SAV')).toBe(true);
    expect((await response(customer, `requests/${request.id}/timeline/`, 'POST', {
      kind: 'observation', observation: 'Tentative interdite', is_internal: false,
    })).status()).toBe(403);
    const foreignClient = (await api(page, 'clients/')).find(client => client.id !== session.user.client);
    expect(foreignClient).toBeTruthy();
    const foreignEquipment = await api(page, 'equipment/', 'POST', {
      client: foreignClient.id, serial_number: `${marker}-AUTRE`, model: 'Autre client fictif',
    });
    const foreignRequest = await api(page, 'requests/', 'POST', {
      equipment: foreignEquipment.id, subject: `${marker} dossier étranger`,
    });
    expect((await customer.request.get(`/api/equipment/${foreignEquipment.id}/timeline/`)).status()).toBe(404);
    expect((await customer.request.get(`/api/requests/${foreignRequest.id}/timeline/`)).status()).toBe(404);

    await login(technician, 'technicien');
    const note = await api(technician, `requests/${request.id}/timeline/`, 'POST', {
      kind: 'observation', observation: `${marker} note du technicien affecté`,
    });
    expect(note.is_internal).toBe(true);
    expect((await response(technician, `requests/${foreignRequest.id}/timeline/`, 'POST', {
      kind: 'observation', observation: 'Tentative hors affectation',
    })).status()).toBe(403);
    expect((await response(technician, `equipment/${foreignEquipment.id}/timeline/`, 'POST', {
      kind: 'summary', summary: 'Tentative hors affectation',
    })).status()).toBe(403);
    const selfAssignment = await response(technician, 'interventions/', 'POST', {
      service_request: foreignRequest.id, technician: assigned.id, diagnosis: 'Tentative de s’attribuer un dossier étranger',
    });
    expect([400, 403]).toContain(selfAssignment.status());
    expect((await response(technician, `requests/${foreignRequest.id}/timeline/`, 'POST', {
      kind: 'observation', observation: 'Nouvelle tentative après auto-affectation refusée',
    })).status()).toBe(403);

    await refresh(customer);
    await navigate(customer, 'Demandes SAV');
    await customer.getByLabel('Rechercher une demande', { exact: true }).fill(marker);
    await customer.locator('.request-workspace-toolbar').getByRole('button', { name: 'Rechercher', exact: true }).click();
    await customer.getByRole('button', { name: `Ouvrir ${request.reference}`, exact: true }).click();
    const customerDialog = customer.getByRole('dialog', { name: 'Dossier SAV', exact: true });
    const customerTimeline = customerDialog.getByRole('region', { name: 'Historique des opérations', exact: true });
    await expect(customerTimeline).toContainText(publicSummary);
    await expect(customerTimeline).not.toContainText(privateNote);
    await expect(customerTimeline).not.toContainText(privateTransitionNote);
    await expect(customerTimeline.getByRole('button', { name: 'Ajouter une opération', exact: true })).toHaveCount(0);
    await customerDialog.getByRole('button', { name: 'Historique de l’onduleur', exact: true }).click();
    await expect(customerTimeline).toContainText(publicSummary);
    await expect(customerTimeline).not.toContainText(privateNote);
  } finally {
    await customerContext.close();
    await technicianContext.close();
  }
});

test('la fiche onduleur ajoute des observations et synthèses puis filtre les véritables événements', async ({ page }) => {
  await login(page);
  const marker = `Suivi-interface-${Date.now()}`;
  const client = (await api(page, 'clients/'))[0];
  const equipment = await api(page, 'equipment/', 'POST', { client: client.id, serial_number: marker, model: 'Onduleur de suivi fictif' });
  const request = await api(page, 'requests/', 'POST', { equipment: equipment.id, subject: marker });
  await refresh(page);
  await navigate(page, 'Demandes SAV');
  await page.getByLabel('Rechercher une demande', { exact: true }).fill(marker);
  await page.locator('.request-workspace-toolbar').getByRole('button', { name: 'Rechercher', exact: true }).click();
  await page.getByRole('button', { name: `Ouvrir ${request.reference}`, exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Dossier SAV', exact: true });
  await dialog.getByRole('button', { name: 'Historique de l’onduleur', exact: true }).click();
  const timeline = dialog.getByRole('region', { name: 'Historique des opérations', exact: true });
  await expect(timeline.locator('ol')).toHaveAttribute('aria-busy', 'false');
  await timeline.getByRole('button', { name: 'Ajouter une opération', exact: true }).click();
  await expect(timeline.getByRole('checkbox', { name: /Note interne/ })).toBeChecked();
  const observation = `${marker} constat technique daté`;
  await timeline.getByLabel('Observation', { exact: true }).fill(observation);
  await timeline.getByRole('button', { name: 'Enregistrer l’opération', exact: true }).click();
  await expect(timeline.locator('.operation-timeline-success')).toContainText('L’observation a été enregistrée.');
  await timeline.getByRole('combobox', { name: 'Afficher', exact: true }).selectOption('observation');
  await expect(timeline.locator('.operation-timeline-list')).toContainText(observation);
  await expect(timeline.locator('.operation-timeline-transition')).toHaveCount(0);
  await timeline.getByRole('combobox', { name: 'Type d’opération', exact: true }).selectOption('summary');
  const summary = `${marker} synthèse de contrôle publiée`;
  await timeline.getByLabel('Synthèse', { exact: true }).fill(summary);
  await timeline.getByRole('checkbox', { name: /Note interne/ }).uncheck();
  await timeline.getByRole('button', { name: 'Enregistrer l’opération', exact: true }).click();
  await expect(timeline.locator('.operation-timeline-success')).toContainText('La synthèse a été enregistrée.');
  await timeline.getByRole('combobox', { name: 'Afficher', exact: true }).selectOption('summary');
  await expect(timeline.locator('.operation-timeline-item')).toHaveCount(1);
  await expect(timeline.locator('.operation-timeline-list')).toContainText(summary);
  await timeline.getByRole('combobox', { name: 'Ordre', exact: true }).selectOption('newest');
  await expect(timeline.locator('time')).toHaveAttribute('datetime', /\d{4}-\d{2}-\d{2}T/);
  await timeline.getByRole('combobox', { name: 'Afficher', exact: true }).selectOption('baseline');
  await expect(timeline.locator('.operation-timeline-item')).toHaveCount(0);
  await expect(timeline).toContainText('Aucune opération ne correspond à ce filtre.');
  const saved = await api(page, `equipment/${equipment.id}/timeline/`);
  expect(saved.find(event => event.observation === observation)).toMatchObject({ is_internal: true, kind: 'observation' });
  expect(saved.find(event => event.summary === summary)).toMatchObject({ is_internal: false, kind: 'summary' });
  expect(saved.some(event => event.source === 'baseline')).toBe(false);
});

test('les fiches de mise en service, préventive et échange conservent leurs contrôles et produisent leur PDF', async ({ page }) => {
  await login(page);
  const marker = `Fiches-${Date.now()}`;
  const client = await api(page, 'clients/', 'POST', { name: marker });
  const equipment = await api(page, 'equipment/', 'POST', { client: client.id, serial_number: `${marker}-ORIGINAL`, model: 'Matériel d’origine fictif' });
  const replacement = await api(page, 'equipment/', 'POST', { client: client.id, serial_number: `${marker}-NOUVEAU`, model: 'Matériel de remplacement fictif' });
  const request = await api(page, 'requests/', 'POST', { equipment: equipment.id, subject: marker });
  const { as_of: today } = await api(page, 'requests/categories/');
  await refresh(page);
  const variants = [
    { kind: 'commissioning', tab: /^Mise en service/, checked: 'Protections électriques vérifiées', key: 'electrical_protection' },
    { kind: 'preventive', tab: /^Préventive/, checked: 'Environnement vérifié', key: 'environment' },
    { kind: 'exchange', tab: /^Échange/ },
  ];
  for (const variant of variants) {
    await navigate(page, 'Demandes SAV');
    await page.getByLabel('Rechercher une demande', { exact: true }).fill(marker);
    await page.locator('.request-workspace-toolbar').getByRole('button', { name: 'Rechercher', exact: true }).click();
    await page.getByRole('button', { name: `Ouvrir ${request.reference}`, exact: true }).click();
    let dialog = page.getByRole('dialog');
    await dialog.getByRole('tab', { name: variant.tab }).click();
    await dialog.getByRole('button', { name: 'Créer une fiche', exact: true }).click();
    dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('combobox', { name: 'Type de fiche', exact: true })).toHaveValue(variant.kind);
    await expect(dialog.getByRole('combobox', { name: 'Demande SAV', exact: true })).toHaveValue(String(request.id));
    await dialog.getByLabel('Date de l’opération', { exact: true }).fill(today);
    await dialog.getByLabel('Site de l’opération', { exact: true }).fill('Site de validation fictif');
    await dialog.getByLabel('N° de série de l’armoire batteries', { exact: true }).fill(`${marker}-ARMOIRE`);
    await dialog.getByLabel('Nombre de batteries', { exact: true }).fill('8');
    await dialog.getByLabel('Contact sur site', { exact: true }).fill('Contact de validation');
    await dialog.getByLabel('Travaux réalisés', { exact: true }).fill(`Travaux de validation ${variant.kind}`);
    await dialog.getByLabel('Synthèse de l’opération', { exact: true }).fill(`${marker} synthèse ${variant.kind}`);
    await dialog.getByRole('combobox', { name: 'Conclusion de la fiche', exact: true }).selectOption('completed');
    await dialog.getByLabel('Notes internes', { exact: true }).fill(`${marker} note réservée aux internes`);
    if (variant.checked) {
      await dialog.getByRole('checkbox', { name: variant.checked, exact: true }).check();
      // A deliberately untouched check remains missing, rather than becoming
      // an operation automatically marked as performed.
      await expect(dialog.getByRole('checkbox', { name: 'Test d’autonomie', exact: true })).not.toBeChecked();
      await dialog.getByLabel('Commentaire de la fiche', { exact: true }).fill(`Contrôle manuel ${variant.kind}`);
    } else {
      const select = dialog.getByRole('combobox', { name: 'Nouvel onduleur de remplacement', exact: true });
      await expect(select.locator(`option[value="${equipment.id}"]`)).toHaveCount(0);
      await select.selectOption(String(replacement.id));
    }
    await dialog.getByRole('combobox', { name: 'Statut', exact: true }).selectOption('completed');
    const savedResponse = page.waitForResponse(result => result.url().endsWith('/api/interventions/') && result.request().method() === 'POST');
    await dialog.getByRole('button', { name: 'Enregistrer', exact: true }).click();
    const result = await savedResponse;
    expect(result.status(), await result.text()).toBe(201);
    const intervention = await result.json();
    expect(intervention).toMatchObject({ kind: variant.kind, service_request: request.id, status: 'completed', performed_on: today, battery_count: 8 });
    if (variant.key) {
      expect(intervention.structured_data[variant.kind][variant.key]).toBe(true);
      expect(Object.hasOwn(intervention.structured_data[variant.kind], 'runtime_test')).toBe(false);
    } else {
      expect(intervention.replacement_equipment).toBe(replacement.id);
      expect((await api(page, `requests/${request.id}/`)).equipment).toBe(equipment.id);
      expect((await api(page, `equipment/${equipment.id}/`)).serial_number).toBe(`${marker}-ORIGINAL`);
    }
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.getByRole('button', { name: `Ouvrir ${request.reference}`, exact: true }).click();
    dialog = page.getByRole('dialog', { name: 'Dossier SAV', exact: true });
    await dialog.getByRole('tab', { name: variant.tab }).click();
    const panel = dialog.getByRole('tabpanel');
    await expect(panel).toContainText(intervention.reference);
    await expect(panel).toContainText(`${marker} synthèse ${variant.kind}`);
    if (variant.checked) {
      await expect(panel.getByRole('checkbox', { name: variant.checked, exact: true })).toBeChecked();
      await expect(panel.getByRole('checkbox', { name: /Test d’autonomie/ })).not.toBeChecked();
      await expect(panel).toContainText('Non renseigné');
    } else await expect(panel).toContainText(`${marker}-NOUVEAU`);
    const link = panel.getByRole('link', { name: 'Rapport PDF', exact: true });
    await expect(link).toHaveAttribute('href', `/api/interventions/${intervention.id}/report/`);
    const pdf = await page.request.get(await link.getAttribute('href'));
    expect(pdf.status()).toBe(200);
    expect(pdf.headers()['content-type']).toContain('application/pdf');
    expect(pdf.headers()['cache-control']).toContain('no-store');
    expect(pdf.headers()['content-disposition']).toContain(intervention.reference);
    expect((await pdf.body()).subarray(0, 5).toString()).toBe('%PDF-');
    await dialog.getByRole('button', { name: 'Fermer', exact: true }).first().click();
  }
});
