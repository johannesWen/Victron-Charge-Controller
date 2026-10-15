import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import * as forecast from '../src/solar-forecast.mjs';

// Exercise the card's lifecycle and render wiring without requiring a browser DOM.
const source = readFileSync(new URL('../src/victron-charge-controller-card.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/registerCard\(\);\s*$/, 'globalThis.Card = VictronChargeControllerCard;');
const template = (strings, ...values) => strings.reduce((text, string, index) => text + string + (values[index] ?? ''), '');
function card() {
  const context = vm.createContext({
    ...forecast, html: template, svg: template, css: template, nothing: '',
    LitElement: class { requestUpdate() {} },
    document: { removeEventListener() {} }, window: { removeEventListener() {} },
    setTimeout, clearTimeout, normalizeView: value => value,
  });
  vm.runInContext(source, context);
  const result = new context.Card();
  result._state = () => undefined;
  result._callService = () => assert.fail('PV view must never call an editing service');
  return result;
}

test('changing chart mode cancels pending edits, picker and tooltip timers without committing', () => {
  const instance = card();
  instance._solarForecast = { usable: true };
  instance._thresholdHoldTimer = setTimeout(() => assert.fail('threshold hold survived'), 60000);
  instance._barHoldTimer = setTimeout(() => assert.fail('bar hold survived'), 60000);
  instance._pickerHideTimer = setTimeout(() => assert.fail('picker timer survived'), 60000);
  instance._tooltipHideTimer = setTimeout(() => assert.fail('tooltip timer survived'), 60000);
  instance.classList = { remove() {} };
  instance._thresholdDrag = { unlocked: true, price: 10, group: { classList: { remove() {} } } };
  instance._pickerBar = { index: 1 };
  instance._tooltipBar = { index: 1 };
  instance._setPlanChartMode('pv');
  assert.equal(instance._planChartMode, 'pv');
  for (const key of ['_thresholdHoldTimer', '_barHoldTimer', '_pickerHideTimer', '_tooltipHideTimer', '_thresholdDrag', '_pickerBar', '_tooltipBar']) {
    assert.equal(instance[key], null, key);
  }
  instance._forecastPoller.onState({ usable: false, reason: 'Forecast unavailable' });
  assert.equal(instance._planChartMode, 'price');
  instance._setPlanChartMode('pv');
  assert.equal(instance._planChartMode, 'price');
});

test('auto-page switch remains visible and explains unavailable forecast without plan/prices', () => {
  const instance = card();
  instance._solarForecast = { usable: false, reason: 'not_configured' };
  const rendered = instance._renderAutoPlanPage();
  assert.match(rendered, /PV forecast view/);
  assert.match(rendered, /\.disabled=true/);
  assert.match(rendered, /not configured/);
  assert.match(rendered, /No charge plan data available/);
});

test('PV view renders both days without prices and includes only forecast interaction handlers', () => {
  const instance = card();
  const start = '2026-10-15T00:00:00+02:00';
  instance._solarForecast = forecast.normalizeForecast({
    usable: true, time_zone: 'Europe/Vienna', source_updated_at: null,
    days: [
      { date: '2026-10-15', start, end: '2026-10-16T00:00:00+02:00' },
      { date: '2026-10-16', start: '2026-10-16T00:00:00+02:00', end: '2026-10-17T00:00:00+02:00' },
    ],
    intervals: [{ start, end: '2026-10-15T00:30:00+02:00', pv_estimate: 0, pv_estimate10: null }],
  });
  instance._setPlanChartMode('pv');
  const rendered = instance._renderAutoPlanPage();
  assert.match(rendered, /Today/);
  assert.match(rendered, /Tomorrow/);
  assert.match(rendered, /Price: unavailable/);
  assert.equal((rendered.match(/Prices not yet available/g) || []).length, 2);
  assert.doesNotMatch(rendered, /plan-picker|threshold-hit|plan-hatch|Current<|Charge Threshold|_setPlanHourAction/);
  assert.match(rendered, /tabindex="0"/);
});
