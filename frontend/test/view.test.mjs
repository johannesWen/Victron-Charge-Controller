import assert from 'node:assert/strict';
import test from 'node:test';

import { normalizeView } from '../src/view.mjs';

test('keeps supported card views', () => {
  assert.equal(normalizeView('settings'), 'settings');
  assert.equal(normalizeView('plan'), 'plan');
  assert.equal(normalizeView('history'), 'history');
});

test('normalizes view values saved with whitespace or different casing', () => {
  assert.equal(normalizeView(' Settings '), 'settings');
  assert.equal(normalizeView('PLAN'), 'plan');
});

test('falls back to settings for missing or legacy view values', () => {
  assert.equal(normalizeView(undefined), 'settings');
  assert.equal(normalizeView('controls'), 'settings');
});
