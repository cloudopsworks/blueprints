const test = require('node:test');
const assert = require('node:assert/strict');
const {handler} = require('./index');
test('function returns ok', () => handler({}, {end: body => assert.equal(body, 'ok')}));
