// node test/connect.test.mjs  — unit tests for the connect-screen helpers.
import test from 'node:test';
import assert from 'node:assert/strict';
import { parseLink, chatUrl, upsert, remove, appHomeUrl } from '../www/connect.mjs';

const TOK = 'AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcde';

test('full pairing link', () => {
  const c = parseLink(`http://192.168.1.20:47821/chat?token=${TOK}`);
  assert.deepEqual(c, { origin: 'http://192.168.1.20:47821', token: TOK, name: '192.168.1.20:47821' });
  assert.equal(chatUrl(c), `http://192.168.1.20:47821/chat?token=${TOK}`);
});

test('link inside a pasted message', () => {
  const c = parseLink(`Open this: http://10.0.0.5:8080/chat?token=${TOK} thanks`);
  assert.equal(c.origin, 'http://10.0.0.5:8080');
  assert.equal(c.token, TOK);
});

test('bare host:port and password-mode URL', () => {
  const c = parseLink('100.64.1.2:8080');
  assert.equal(c.origin, 'http://100.64.1.2:8080');
  assert.equal(c.token, null);
  assert.equal(chatUrl(c), 'http://100.64.1.2:8080/chat');
  assert.equal(parseLink('https://claws.example.com/chat').origin, 'https://claws.example.com');
});

test('rejects junk with a readable message', () => {
  assert.throws(() => parseLink(''), /Paste the link/);
  assert.throws(() => parseLink('javascript:alert(1)'), /link|http/i);
  assert.throws(() => parseLink('ftp://host/x'), /http/);
  assert.throws(() => parseLink('http://host:1/chat?token=bad token!'), /damaged/);
});

test('token is URL-encoded into chat URL', () => {
  assert.equal(chatUrl({ origin: 'http://h:1', token: 'a-b_c' }), 'http://h:1/chat?token=a-b_c');
});

test('upsert keeps most recent first and dedupes by origin', () => {
  let list = [];
  list = upsert(list, { origin: 'http://a:1', token: null, name: 'a' }, 1);
  list = upsert(list, { origin: 'http://b:1', token: null, name: 'b' }, 2);
  list = upsert(list, { origin: 'http://a:1', token: TOK, name: 'a' }, 3);
  assert.deepEqual(list.map((c) => c.origin), ['http://a:1', 'http://b:1']);
  assert.equal(list[0].token, TOK);
  assert.deepEqual(remove(list, 'http://a:1').map((c) => c.origin), ['http://b:1']);
});

test('app home URL per platform', () => {
  assert.equal(appHomeUrl('Mozilla/5.0 (Linux; Android 14) CheetahClawsApp/0.1'), 'https://localhost/?switch=1');
  assert.equal(appHomeUrl('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0) CheetahClawsApp/0.1'), 'capacitor://localhost/?switch=1');
});
