import { test, expect } from '@playwright/test';
import { openLegacyDashboard } from './legacy_navigation.js';

const password = process.env.TVM_DEMO_PASSWORD;
const marker = () => `LAB-IA-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

async function login(page, username = 'admin') {
  await page.goto('/');
  await page.getByLabel('Identifiant', { exact: true }).fill(username);
  await page.getByLabel('Mot de passe', { exact: true }).fill(password);
  const loaded = page.waitForResponse(r => new URL(r.url()).pathname === '/api/dashboard/' && r.ok());
  await page.getByRole('button', { name: /Se connecter/i }).click();
  await loaded;
  await openLegacyDashboard(page);
}

async function response(page, path, method = 'GET', data) {
  const { csrfToken } = await (await page.request.get('/api/session/')).json();
  return page.request.fetch(`/api/${path}`, { method, data, headers: { 'X-CSRFToken': csrfToken } });
}

async function api(page, path, method = 'GET', data) {
  const result = await response(page, path, method, data);
  expect(result.ok(), `${method} ${path}: ${await result.text()}`).toBeTruthy();
  return result.json();
}

async function assistant(page) {
  const nav = page.getByRole('navigation', { name: 'Navigation principale' });
  if (!await nav.isVisible()) await page.getByRole('button', { name: 'Ouvrir le menu', exact: true }).click();
  await nav.getByText('Assistant diagnostic', { exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Assistant diagnostic', exact: true })).toBeVisible();
}

test('une vraie source importée reste brouillon puis devient recherchable après approbation, sans faux diagnostic hors connexion IA', async ({ page }) => {
  await login(page);
  const model = marker();
  const title = `Manuel fictif ${model}`;
  const text = 'Code F42 : autonomie réduite. Contrôler visuellement les batteries après consignation. Vérifier les connexions selon la procédure du fabricant.';
  const status = await api(page, 'diagnostics/status/');
  expect(status).toMatchObject({ enabled: false, configured: false, operational: false });
  await assistant(page);
  await page.getByRole('button', { name: 'Bibliothèque', exact: true }).click();
  await page.getByRole('button', { name: 'Ajouter un document', exact: true }).click();
  const upload = page.getByRole('dialog', { name: 'Ajouter un document technique', exact: true });
  await upload.getByLabel('Fichier PDF ou TXT', { exact: true }).setInputFiles({ name: 'manuel-fictif.txt', mimeType: 'text/plain', buffer: Buffer.from(text) });
  await upload.getByLabel('Titre du document', { exact: true }).fill(title);
  await upload.getByLabel('Marque du document', { exact: true }).fill('Eaton');
  await upload.getByLabel('Modèle du document', { exact: true }).fill(model);
  const posted = page.waitForResponse(r => new URL(r.url()).pathname === '/api/knowledge/documents/' && r.request().method() === 'POST');
  await upload.getByRole('button', { name: 'Enregistrer le brouillon', exact: true }).click();
  const documentResponse = await posted;
  expect(documentResponse.status()).toBe(201);
  const document = await documentResponse.json();
  expect(document).toMatchObject({ state: 'draft', model, text_status: 'extracted' });
  await expect(upload).toHaveCount(0);
  const input = { brand: 'Eaton', model, symptoms: 'autonomie réduite batteries', fault_code: 'F42', measurements: '' };
  const unpublished = await api(page, 'diagnostics/search/', 'POST', input);
  expect(unpublished.sources).toEqual([]);
  await page.locator('.diagnostic-document-card').filter({ hasText: title }).click();
  const sourceDialog = page.getByRole('dialog', { name: title, exact: true });
  await expect(sourceDialog).toContainText(text);
  await sourceDialog.getByRole('button', { name: 'Approuver la source', exact: true }).click();
  await expect(sourceDialog.locator('.diagnostic-state')).toHaveText('Approuvé');
  await sourceDialog.getByRole('button', { name: 'Fermer', exact: true }).last().click();
  await page.getByRole('button', { name: 'Diagnostic', exact: true }).click();
  await page.getByLabel('Modèle', { exact: true }).fill(model);
  await page.getByLabel('Symptômes', { exact: true }).fill(input.symptoms);
  await page.getByLabel('Code défaut (facultatif)', { exact: true }).fill('F42');
  await page.getByRole('button', { name: 'Rechercher les sources', exact: true }).click();
  const results = page.getByRole('region', { name: 'Résultats du diagnostic' });
  await expect(results).toContainText(title);
  await expect(results).toContainText('page 1');
  await expect(results.locator('.diagnostic-source')).toHaveCount(1);
  await page.getByLabel('J’autorise le partage de cette saisie technique et des extraits approuvés avec le fournisseur IA configuré.', { exact: true }).check();
  const analysis = page.waitForResponse(r => new URL(r.url()).pathname === '/api/diagnostics/analyze/' && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Analyser avec IA', exact: true }).click();
  const analysisResponse = await analysis;
  expect(analysisResponse.ok()).toBeTruthy();
  const run = await analysisResponse.json();
  expect(run).toMatchObject({ status: 'requires_configuration', output: null });
  expect(run.sources).toHaveLength(1);
  await expect(results).toContainText('IA à connecter');
  await expect(results.locator('.diagnostic-output')).toHaveCount(0);
  await page.getByRole('button', { name: 'Historique', exact: true }).click();
  await expect(page.locator('.diagnostic-history-row').filter({ hasText: model })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('le retour technique exige une intervention terminée, une approbation et conserve la traçabilité après archivage', async ({ page }) => {
  await login(page);
  const model = marker();
  const company = await api(page, 'clients/', 'POST', { name: `Centre fictif ${model}`, email: 'centre-ia@example.invalid' });
  const unit = await api(page, 'equipment/', 'POST', { client: company.id, serial_number: `SN-${model}`, brand: 'Eaton', model });
  const call = await api(page, 'requests/', 'POST', { equipment: unit.id, subject: 'Test technique fictif', description: 'NOTE CLIENT A NE PAS COPIER', status: 'maintenance' });
  const visit = await api(page, 'interventions/', 'POST', { service_request: call.id, status: 'completed', work_done: 'Essais fictifs terminés', performed_on: new Date().toISOString().slice(0, 10) });
  await page.reload();
  await openLegacyDashboard(page);
  await assistant(page);
  await page.getByRole('button', { name: 'Retours validés', exact: true }).click();
  await page.getByRole('button', { name: 'Proposer un retour', exact: true }).click();
  const form = page.getByRole('dialog', { name: 'Proposer un retour d’intervention', exact: true });
  await form.getByLabel('Intervention terminée', { exact: true }).selectOption(String(visit.id));
  await form.getByLabel('Symptômes constatés', { exact: true }).fill('Autonomie réduite après contrôle sur banc fictif');
  await form.getByLabel('Mesures effectuées', { exact: true }).fill('Contrôle hors tension des connexions');
  await form.getByLabel('Cause confirmée', { exact: true }).fill('Batteries en fin de vie confirmées');
  await form.getByLabel('Réparation effectuée', { exact: true }).fill('Remplacement des batteries selon procédure');
  await form.getByLabel('Résultat', { exact: true }).fill('Autonomie nominale vérifiée sur banc fictif');
  const posted = page.waitForResponse(r => new URL(r.url()).pathname === '/api/knowledge/cases/' && r.request().method() === 'POST');
  await form.getByRole('button', { name: 'Enregistrer le retour brouillon', exact: true }).click();
  const caseResponse = await posted;
  expect(caseResponse.status()).toBe(201);
  const repairCase = await caseResponse.json();
  expect(repairCase.state).toBe('draft');
  expect(JSON.stringify(repairCase)).not.toContain('NOTE CLIENT A NE PAS COPIER');
  expect(JSON.stringify(repairCase)).not.toContain(unit.serial_number);
  const card = page.locator('.diagnostic-case-row').filter({ hasText: model });
  await card.click();
  const detail = page.getByRole('dialog', { name: `Retour technique · ${model}` });
  await detail.getByRole('button', { name: 'Approuver la source', exact: true }).click();
  await expect(detail.locator('.diagnostic-state')).toHaveText('Approuvé');
  await detail.getByRole('button', { name: 'Fermer', exact: true }).last().click();
  const input = { brand: 'Eaton', model, symptoms: 'Autonomie réduite batteries' };
  const found = await api(page, 'diagnostics/search/', 'POST', input);
  expect(found.sources.some(source => source.id === `R${repairCase.id}`)).toBe(true);
  await card.click();
  await detail.getByRole('button', { name: 'Archiver la source', exact: true }).click();
  await detail.getByRole('button', { name: 'Confirmer l’archivage', exact: true }).click();
  await expect(detail.locator('.diagnostic-state')).toHaveText('Archivé');
  expect((await api(page, 'diagnostics/search/', 'POST', input)).sources).toEqual([]);
});

test('le portail client ne voit pas l’assistant et ne peut lire la bibliothèque, les téléchargements ou les analyses', async ({ page }) => {
  await login(page, 'client');
  await expect(page.getByRole('navigation', { name: 'Navigation principale' }).getByText('Assistant diagnostic', { exact: true })).toHaveCount(0);
  for (const path of ['knowledge/documents/', 'knowledge/documents/1/download/', 'knowledge/cases/', 'diagnostics/status/', 'diagnostics/runs/', 'diagnostics/runs/1/']) {
    expect((await response(page, path)).status(), path).toBe(403);
  }
  expect((await response(page, 'diagnostics/analyze/', 'POST', { model: 'LAB', symptoms: 'Batteries', request_key: '00000000-0000-4000-8000-000000000001' })).status()).toBe(403);
});

test('une réponse fournisseur simulée affiche les hypothèses et ouvre les vraies sources citées sans action métier', async ({ page }) => {
  await login(page);
  const model = marker();
  const { csrfToken } = await (await page.request.get('/api/session/')).json();
  const uploaded = await page.request.post('/api/knowledge/documents/', {
    headers: { 'X-CSRFToken': csrfToken },
    multipart: { title: `Notice fictive de rendu ${model}`, brand: 'Eaton', model, kind: 'manual',
      file: { name: 'notice-rendu-fictive.txt', mimeType: 'text/plain', buffer: Buffer.from('Autonomie batterie réduite : suivre la procédure de contrôle hors tension du fabricant avant remplacement.') } },
  });
  expect(uploaded.status()).toBe(201);
  const document = await uploaded.json();
  await api(page, `knowledge/documents/${document.id}/approve/`, 'POST', {});
  const search = await api(page, 'diagnostics/search/', 'POST', { brand: 'Eaton', model, symptoms: 'autonomie batterie réduite' });
  expect(search.sources).toHaveLength(1);
  const source = search.sources[0];
  const intercepted = [];
  // UI-only provider fixture. The server remains disabled; no paid API call.
  await page.route('**/api/diagnostics/analyze/', async route => {
    intercepted.push(route.request().postDataJSON());
    await route.fulfill({ json: { id: 900000001, status: 'completed', sources: [{ ...source, available: true }], warnings: [],
      output: { summary: 'Exemple fictif de présentation, à valider.',
        hypotheses: [{ title: 'Vieillissement des batteries à vérifier', explanation: 'Le manuel documente un contrôle de l’autonomie.', source_ids: [source.id] }],
        checks: [{ instructions: 'Consulter la procédure du fabricant et faire contrôler hors tension par un technicien habilité.', source_ids: [source.id] }],
        missing_information: ['Résultat du contrôle d’autonomie'], uncertainties: ['La cause reste à confirmer.'] } } });
  });
  await assistant(page);
  await page.getByLabel('Modèle', { exact: true }).fill(model);
  await page.getByLabel('Symptômes', { exact: true }).fill('autonomie batterie réduite');
  await expect(page.getByRole('button', { name: 'Analyser avec IA', exact: true })).toBeDisabled();
  await page.getByLabel('J’autorise le partage de cette saisie technique et des extraits approuvés avec le fournisseur IA configuré.', { exact: true }).check();
  await page.getByRole('button', { name: 'Analyser avec IA', exact: true }).click();
  const results = page.getByRole('region', { name: 'Résultats du diagnostic' });
  await expect(results.getByRole('heading', { name: 'Hypothèses à vérifier' })).toBeVisible();
  await expect(results).toContainText('Vieillissement des batteries à vérifier');
  await expect(results).toContainText('Résultat du contrôle d’autonomie');
  await results.locator('.diagnostic-citations a').first().click();
  await expect(results.locator('.diagnostic-source')).toBeFocused();
  await results.getByRole('button', { name: 'Consulter la source', exact: true }).click();
  const detail = page.getByRole('dialog', { name: document.title, exact: true });
  await expect(detail).toContainText('Page 1 · extrait 1');
  expect(intercepted).toHaveLength(1);
  expect(intercepted[0].request_key).toMatch(/^[0-9a-f-]{36}$/);
  expect(intercepted[0].model).toBe(model);
});
