// Static exports must never initialize either goal controller, including recovery.
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../godseye/static/app.js'), 'utf8');
test('static demo disables live and mock goal transport before DOM, storage or network access', () => {
  const mock = source.slice(source.indexOf('// Goal workflow:'), source.indexOf('// End goal workflow.'));
  const live = source.slice(source.indexOf('// Live goal transport.'), source.lastIndexOf('initialize();'));
  for (const controller of [mock, live]) {
    // No DOM, storage, contract, location or network exists here. Access would throw.
    vm.runInNewContext(controller, {staticDemo: true});
  }
});
