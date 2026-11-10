const provider = document.getElementById('provider');
const routing = document.getElementById('routing');
const form = document.getElementById('settings');
const key = document.getElementById('key');
const model = document.getElementById('model');
const result = document.getElementById('result');
function showStatus(data) {
  document.getElementById('saved').textContent = data.configured ? 'A key is saved. Leave the key field blank to keep it, or paste a replacement.' : 'No key saved yet.';
  key.required = !data.configured;
  document.getElementById('location').textContent = 'Private settings folder: ' + data.directory;
  document.getElementById('next').textContent = data.configured ? 'Ready for the next agent: load ' + data.env_file + ' before following the isolated-evaluator launch guide. No experiment has started.' : '';
}
let statusGeneration = 0;
async function loadStatus(selected) {
  const generation = ++statusGeneration;
  document.getElementById('save').disabled = true;
  key.value = '';
  try {
    const response = await fetch('/status' + (selected ? '?provider=' + selected : ''));
    const data = await response.json();
    if (generation !== statusGeneration) return;
    if (!response.ok) throw new Error(data.error);
    provider.value = data.provider;
    model.value = data.model;
    routing.value = data.routing;
    document.getElementById('routing-options').hidden = data.provider !== 'openrouter';
    const links = {openai:'https://platform.openai.com/api-keys', openrouter:'https://openrouter.ai/settings/keys', huggingface:'https://huggingface.co/settings/tokens'};
    document.getElementById('key-link').href = links[data.provider];
    key.placeholder = data.provider === 'huggingface' ? 'hf_…' : 'sk-…';
    showStatus(data);
    result.textContent = '';
    document.getElementById('save').disabled = false;
  } catch (error) {
    if (generation === statusGeneration) {result.className='status error';result.textContent=error.message;}
  }
}
provider.addEventListener('change', () => loadStatus(provider.value));
loadStatus();
form.addEventListener('submit',async event=>{
  event.preventDefault();
  const button=document.getElementById('save');button.disabled=true;provider.disabled=true;
  result.className='status';result.textContent='Saving on this computer…';
  try {
    const response=await fetch('/save',{method:'POST',headers:{'Content-Type':'application/json','X-Setup-Token':document.querySelector('meta[name="setup-token"]').content},body:JSON.stringify({key:key.value,model:model.value,provider:provider.value,routing:routing.value})});
    const data=await response.json();
    if(!response.ok)throw new Error(data.error || 'Save failed');
    showStatus(data);result.className='status success';result.textContent='Saved locally. You can close this tab.\nNo model requests were made.';
  }catch(e){result.className='status error';result.textContent=e.message;}
  finally{key.value='';button.disabled=false;provider.disabled=false;}
});
