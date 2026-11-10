const $ = id => document.getElementById(id);
const provider = $('provider');
const routing = $('routing');
const form = $('settings');
const key = $('key');
const model = $('model');
const result = $('result');
let models = [];
let busy = false;
let statusGeneration = 0;
function setBusy(value) {
  busy = value;
  for (const element of form.querySelectorAll('input, select, button')) element.disabled = value;
  form.setAttribute('aria-busy', String(value));
}
function message(element, text, state = '') {
  element.className = 'status' + (state === 'success' ? ' success' : state && state !== 'loading' ? ' error' : '');
  element.dataset.state = state;
  element.textContent = text;
}
function showStatus(data) {
  $('saved').textContent = data.configured ? 'A key is saved. Leave the key field blank to keep it, or paste a replacement.' : 'No key saved yet.';
  key.required = !data.configured;
  $('location').textContent = 'Private settings folder: ' + data.directory;
  $('next').textContent = data.configured ? 'Load ' + data.env_file + ' before following the isolated-evaluator launch guide. No experiment has started.' : '';
}
function showSupport() {
  const entry = models.find(item => item.id === model.value.trim());
  $('tool-support').textContent = entry && entry.tool_support === 'supported'
    ? 'Tool support: confirmed by catalog metadata. ' + entry.tool_support_source + '. Route/account access still unverified.'
    : 'Tool support: unknown. No confirming metadata for this exact model ID and route.';
}
function renderModels() {
  const query = $('model-search').value.trim().toLowerCase();
  const matches = models.filter(item => item.id.toLowerCase().includes(query));
  $('model-list').replaceChildren();
  for (const entry of matches) {
    const option = document.createElement('option');
    option.value = entry.id;
    option.textContent = entry.id + (entry.tool_support === 'supported' ? ' · tools: metadata confirmed' : ' · tools: unknown');
    $('model-list').append(option);
  }
  $('model-list').value = model.value.trim();
  message($('catalog-status'), `${matches.length} of ${models.length} models shown. Catalog listing does not verify account access.`, 'success');
}
function resetCatalog() {
  models = [];
  $('catalog').hidden = true;
  $('model-search').value = '';
  $('model-list').replaceChildren();
  message($('catalog-status'), 'Models have not been loaded.');
  message($('test-status'), '');
  showSupport();
}
async function post(path, body) {
  let response, data;
  try {
    response = await fetch(path, {method: 'POST', headers: {
      'Content-Type': 'application/json', 'X-Setup-Token': document.querySelector('meta[name="setup-token"]').content
    }, body: JSON.stringify(body)});
    data = await response.json();
  } catch (_) {
    throw {state: 'connection_failed', error: 'Local setup connection failed. No automatic retry. A connection test may still have been billed.'};
  }
  if (!response.ok) throw data;
  return data;
}
function inputs() {
  return {provider: provider.value, key: key.value, model: model.value, routing: routing.value};
}
async function loadStatus(selected) {
  const generation = ++statusGeneration;
  setBusy(true);
  key.value = '';
  resetCatalog();
  try {
    const response = await fetch('/status' + (selected ? '?provider=' + selected : ''));
    const data = await response.json();
    if (generation !== statusGeneration) return;
    if (!response.ok) throw data;
    provider.value = data.provider;
    model.value = data.model;
    routing.value = data.routing;
    $('routing-options').hidden = data.provider !== 'openrouter';
    const links = {openai: 'https://platform.openai.com/api-keys', openrouter: 'https://openrouter.ai/settings/keys', huggingface: 'https://huggingface.co/settings/tokens'};
    $('key-link').href = links[data.provider];
    key.placeholder = data.provider === 'huggingface' ? 'hf_…' : 'sk-…';
    showStatus(data);
    showSupport();
    message(result, '');
    setBusy(false);
  } catch (_) {
    if (generation === statusGeneration) {
      message(result, 'Cannot load local settings. Reopen setup to try again.', 'settings_unavailable');
      // Avoid saving defaults over a profile whose status failed to load.
      provider.disabled = false;
    }
  }
}
provider.addEventListener('change', () => loadStatus(provider.value));
$('model-search').addEventListener('input', renderModels);
$('model-list').addEventListener('change', () => {
  model.value = $('model-list').value;
  showSupport();
  message($('test-status'), '');
});
model.addEventListener('input', () => {showSupport(); message($('test-status'), '');});
routing.addEventListener('change', () => message($('test-status'), ''));
key.addEventListener('input', () => {resetCatalog(); message($('test-status'), '');});
$('load-models').addEventListener('click', async () => {
  if (busy) return;
  const body = inputs();
  setBusy(true);
  resetCatalog();
  message($('catalog-status'), 'Loading provider catalog…', 'loading');
  try {
    const data = await post('/models', body);
    models = data.models;
    $('catalog').hidden = false;
    renderModels();
    showSupport();
  } catch (error) {
    message($('catalog-status'), error.error || 'Could not load models.', error.state || 'failed');
  } finally {setBusy(false);}
});
$('test-connection').addEventListener('click', async () => {
  if (busy) return;
  const body = inputs();
  if (!body.model.trim()) {
    message($('test-status'), 'Choose or enter a model ID first.', 'invalid_request');
    return;
  }
  if (!window.confirm(`Send one potentially billable request to ${body.provider} for ${body.model.trim()}?\n\nOutput limit: 128 tokens. No retries, tool execution, or experiment. A timeout may still be billed. Routing preference: ${body.routing}.`)) return;
  setBusy(true);
  message($('test-status'), 'Testing connection and tool calling with one request…', 'loading');
  try {
    const data = await post('/test-connection', {...body, confirmed: true});
    message($('test-status'), data.message, data.state);
  } catch (error) {
    message($('test-status'), error.error || 'Connection test failed. No automatic retry.', error.state || 'failed');
  } finally {setBusy(false);}
});
form.addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  const body = inputs();
  setBusy(true);
  message(result, 'Saving on this computer…', 'loading');
  try {
    const data = await post('/save', body);
    showStatus(data);
    message(result, 'Saved locally. Saving made no provider requests and started no experiment.', 'success');
  } catch (error) {
    message(result, error.error || 'Save failed.', error.state || 'failed');
  } finally {key.value = ''; resetCatalog(); setBusy(false);}
});
loadStatus();
