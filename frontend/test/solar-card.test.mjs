import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import * as forecast from '../src/solar-forecast.mjs';

// Exercise the card's lifecycle and render wiring without requiring a browser DOM.
const source = readFileSync(new URL('../src/victron-charge-controller-card.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/registerCard\(\);\s*$/, 'globalThis.Card = VictronChargeControllerCard;');
const template = (strings, ...values) => strings.reduce((text, string, index) => text + string + (values[index] ?? ''), '');
function card({ now = '2026-10-15T00:15:00+02:00', templates = [] } = {}) {
  const render = (strings, ...values) => {
    const rendered = template(strings, ...values);
    templates.push({ strings, values, rendered });
    return rendered;
  };
  const context = vm.createContext({
    ...forecast, html: render, svg: render, css: template, nothing: '',
    LitElement: class { requestUpdate() {} },
    document: { addEventListener() {}, removeEventListener() {} }, window: { removeEventListener() {} },
    setTimeout, clearTimeout,
    Date: class extends Date { static now() { return Date.parse(typeof now === 'function' ? now() : now); } },
    normalizeView: value => value,
  });
  vm.runInContext(source, context);
  const result = new context.Card();
  result._state = () => undefined;
  result.hass = { callService: () => assert.fail('Rendering or switching views must never edit the schedule') };
  result._val = () => undefined;
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

test('PV view renders accessible forecasts on both days without prices or editable actions', () => {
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
  assert.match(rendered, /Today <span class="plan-chart-date">2026-10-15<\/span> - PV 10%: unavailable - PV: 0.0 kWh/);
  assert.match(rendered, /Tomorrow <span class="plan-chart-date">2026-10-16<\/span> - PV 10%: unavailable - PV: unavailable/);
  assert.match(rendered, /Price: unavailable/);
  assert.equal((rendered.match(/Prices not yet available/g) || []).length, 2);
  assert.doesNotMatch(rendered, /class="plan-picker"|threshold-hit|Charge Threshold|_setPlanHourAction/);
  assert.match(rendered, /tabindex="0"/);
  assert.equal((rendered.match(/data-readonly=true/g) || []).length, 49);
  assert.doesNotMatch(rendered, /Change hour action/);
});

for (const prices of [[5, 20], [-10, 20], [-20, -5], [0, 0], []]) {
  test(`PV areas and price bars share zero on both days with prices ${JSON.stringify(prices)}`, () => {
    const instance = card();
    const hour = 3600000;
    const days = [0, 1].map(index => ({
      date: `2026-10-${15 + index}`,
      start: Date.UTC(2026, 9, 15 + index), end: Date.UTC(2026, 9, 16 + index),
    }));
    const charts = forecast.buildForecastCharts({
      time_zone: 'UTC', days,
      intervals: days.flatMap(day => [
        { start: day.start, end: day.start + hour, pv_estimate: 0, pv_estimate10: 0 },
        { start: day.start + hour, end: day.start + 2 * hour, pv_estimate: 4, pv_estimate10: 2 },
      ]),
    }, days.flatMap(day => prices.map((price, hour) => ({ date: day.date, hour, price }))));
    const baseline = 240 + charts.priceMin / (charts.priceMax - charts.priceMin) * 202;
    assert.ok(baseline >= 139 && baseline <= 240, 'PV retains at least half the plot height');
    for (const day of charts.days) {
      const rendered = instance._renderSolarChart(day, charts, 'UTC');
      const paths = [...rendered.matchAll(/<path d=(.*?) fill=/g)];
      assert.equal(paths.length, 2);
      for (const [, path] of paths) {
        const points = [...path.matchAll(/[ML] ([\d.e+-]+) ([\d.e+-]+)/g)].map(match => match.slice(1).map(Number));
        assert.equal(points[0][1], baseline, 'fill starts at price zero');
        assert.equal(points[1][1], baseline, 'zero production is at price zero');
        assert.equal(points.at(-1)[1], baseline, 'fill closes at price zero');
        assert.ok(points.every(([, y]) => y >= 38 && y <= baseline));
        assert.ok(points.some(([, y]) => y < baseline), 'positive PV extends above zero');
      }
      const bars = [...rendered.matchAll(/<rect class="plan-price-bar"\s+x="[^"]+" y="([^"]+)" width="[^"]+" height="([^"]+)"/g)];
      assert.equal(bars.length, prices.length);
      bars.forEach(([, y, height], index) => {
        if (prices[index] === 0) { assert.equal(Number(y), baseline); assert.equal(Number(height), 1); }
        else assert.ok(Math.abs(Number(y) + (prices[index] > 0 ? Number(height) : 0) - baseline) < 1e-9);
      });
      const pvTicks = [...rendered.matchAll(/<text x=556 y=(\S+) class="plan-axis-label">([^<]+)</g)];
      assert.equal(pvTicks.length, 5);
      for (const [, y, label] of pvTicks) {
        const power = (baseline - (Number(y) - 4)) / (baseline - 38) * charts.pvMax;
        assert.ok(Math.abs(Number(label) - power) <= 0.051, 'PV axis matches the plotted scale');
      }
    }
  });
}

// Capture template event bindings so these checks exercise the actual rendered handlers.
const nodes = (templates, className) => templates.filter(node => node.strings.join('').includes(`class="${className}"`));
function handler(node, name) {
  const index = node.strings.findIndex(string => string.endsWith(`@${name}=`));
  assert.notEqual(index, -1, `${name} binding exists`);
  return node.values[index];
}
const event = (dataset = {}, extra = {}) => ({
  currentTarget: { dataset, closest: () => null, focus() {} }, preventDefault() {}, stopPropagation() {}, ...extra,
});
function chartsFor(plan = [], start = '2026-10-25T00:00:00+02:00', middle = '2026-10-26T00:00:00+01:00', end = '2026-10-27T00:00:00+01:00') {
  const input = forecast.normalizeForecast({
    usable: true, time_zone: 'Europe/Vienna',
    days: [{ date: start.slice(0, 10), start, end: middle }, { date: middle.slice(0, 10), start: middle, end }],
    intervals: [0, 2, 3].map(hour => ({ start: new Date(Date.parse(start) + hour * 3600000).toISOString(),
      end: new Date(Date.parse(start) + hour * 3600000 + 1800000).toISOString(), pv_estimate: 2, pv_estimate10: 1 })),
  });
  return forecast.buildForecastCharts(input, plan);
}

test('PV and Price share action colors, PV columns, hatching, and past-hour styling', () => {
  const instance = card({ now: '2026-10-24T12:00:00Z' });
  const plan = [
    { hour: 0, price: 10, action: 'idle' },
    { hour: 1, price: 12, action: 'charge', blockedDischarging: true },
    { hour: 2, price: -4, displayAction: 'discharge', blockedCharging: true },
    { hour: 3, price: 0, displayAction: 'pv_charge' },
    { hour: 4, price: 3, displayAction: 'blocked', blockedCharging: true, blockedDischarging: true },
  ].map(entry => ({ date: '2026-10-25', ...entry }));
  const charts = chartsFor(plan);
  const pv = instance._renderSolarChart(charts.days[0], charts, 'Europe/Vienna');
  const price = instance._renderPriceChart(plan);
  for (const rendered of [pv, price]) {
    assert.match(rendered, /fill="var\(--vcc-success, #4caf50\)"/);
    assert.match(rendered, /fill="#ff6600"/);
    assert.match(rendered, /fill="var\(--vcc-disabled, #bdbdbd\)"/);
    assert.match(rendered, /fill="var\(--vcc-blocked-both, #f44336\)"/);
    assert.match(rendered, /class="plan-pv-column"/);
    for (const suffix of ['charging', 'discharging', 'both']) assert.match(rendered, new RegExp(`fill="url\\(#plan-hatch-blocked-${suffix}\\)"`));
  }
  const past = card({ now: '2026-10-26T00:00:00+01:00' })._renderSolarChart(charts.days[0], charts, 'Europe/Vienna');
  assert.doesNotMatch(past, /fill="url\(#plan-hatch|class="plan-pv-column"/);
  assert.equal((past.match(/\sopacity="0.35"/g) || []).length, 6, 'both repeated hour bars are past');
});

for (const now of ['2026-10-25T00:30:00+02:00', '2026-10-25T02:30:00+02:00', '2026-10-25T02:30:00+01:00', '2026-10-25T23:59:00+01:00', '2026-10-26T00:00:00+01:00']) {
  test(`PV current-hour indicator follows HA timezone and absolute DST interval at ${now}`, () => {
    const templates = [], instance = card({ now, templates }), charts = chartsFor();
    charts.days.forEach(day => instance._renderSolarChart(day, charts, 'Europe/Vienna'));
    const markers = templates.filter(node => node.strings.join('').includes('stroke-dasharray="4,3"'));
    assert.equal(markers.length, 1, 'only the absolute current interval is marked');
    const labels = templates.filter(node => node.strings.join('').includes('class="plan-axis-label ') && node.rendered.includes('plan-current-hour'));
    assert.equal(labels.length, 1);
    const target = charts.days.flatMap(day => day.hours).find(hour => hour.start <= Date.parse(now) && Date.parse(now) < hour.end);
    assert.ok(labels[0].rendered.includes(`>${String(target.hour).padStart(2, '0')}:${String(target.minute || 0).padStart(2, '0')}</text>`));
    const chart = charts.days.find(day => day.start <= Date.parse(now) && Date.parse(now) < day.end);
    const expectedX = 50 + (target.start - chart.start) / (chart.end - chart.start) * 500;
    assert.ok(markers[0].rendered.includes(`x="${expectedX}"`), 'outline belongs to the correct repeated hour');
  });
}

test('PV half-hour tooltip remains on tap; hold, context menu and keyboard map repeated hours to the shared picker', t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const templates = [], instance = card({ now: '2026-10-25T01:00:00+02:00', templates });
  const charts = chartsFor([{ date: '2026-10-25', hour: 2, price: -4, action: 'charge' }]);
  const day = charts.days[0], chartId = `solar-${day.date}`;
  instance._renderSolarChart(day, charts, 'Europe/Vienna');
  const slots = nodes(templates, 'solar-slot');
  day.slots.forEach((slot, index) => {
    if (day.hours[slot.hourIndex].hour !== 2) return;
    handler(slots[index], 'click')(event());
    assert.equal(instance._solarTooltip.index, index);
    assert.equal(instance._pickerBar, null);
    for (const name of ['contextmenu', 'pointerdown', 'keydown']) {
      handler(slots[index], name)(event({}, { key: 'Enter', button: 0, clientX: 110, clientY: 80 }));
      if (name === 'pointerdown') t.mock.timers.tick(500);
      assert.equal(instance._pickerBar.chartId, chartId);
      assert.equal(instance._pickerBar.index, slot.hourIndex);
      assert.equal(instance._solarTooltip, null);
      instance._closePicker();
      instance._barLongPressFired = false;
    }
  });
});

for (const action of ['charge', 'pv_charge', 'discharge', 'idle']) test(`PV picker sends ${action} with civil date/hour, updates optimistically and rolls back on failure`, async () => {
  const templates = [], instance = card({ now: '2026-10-24T12:00:00Z', templates });
  const charts = chartsFor([{ date: '2026-10-25', hour: 2, price: 0, action: 'idle' }]);
  const hourIndex = charts.days[0].hours.findLastIndex(hour => hour.hour === 2);
  instance._openPicker('solar-2026-10-25', hourIndex);
  instance._renderSolarChart(charts.days[0], charts, 'Europe/Vienna');
  const button = nodes(templates, 'plan-picker-btn').find(node => node.rendered.includes(`data-action=${action} `));
  assert.ok(button);
  let reject;
  instance.hass.callService = (domain, service, data) => {
    assert.equal(domain, 'victron_charge_control'); assert.equal(service, 'set_hour_action');
    assert.equal(JSON.stringify(data), JSON.stringify({ hour: 2, action, date: '2026-10-25' }));
    return new Promise((_, fail) => { reject = fail; });
  };
  if (action === 'charge') handler(button, 'keydown')(event({}, { key: 'Enter' }));
  else handler(button, 'click')(event());
  assert.equal(instance._pendingPlanActions['2026-10-25:2'].action, action);
  assert.equal(instance._pickerBar, null);
  const enriched = instance._enrichPlanDisplayState([{ date: '2026-10-25', hour: 2, action: 'idle' }]);
  assert.equal(enriched[0].displayAction, action);
  reject(new Error('Test service failed'));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(instance._pendingPlanActions['2026-10-25:2'], undefined);
  assert.equal(instance._lastServiceError.message, 'Test service failed');
});

test('unpriced and past PV slots block every editing gesture while retaining forecast tooltips', t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const templates = [], instance = card({ now: '2026-10-25T01:00:00+02:00', templates });
  const charts = chartsFor([{ date: '2026-10-25', hour: 0, price: 1 }]);
  instance._renderSolarChart(charts.days[0], charts, 'Europe/Vienna');
  nodes(templates, 'solar-slot').forEach((node, index) => {
    const slot = charts.days[0].slots[index];
    const dataset = { past: charts.days[0].hours[slot.hourIndex].end <= Date.parse('2026-10-25T01:00:00+02:00') ? 'true' : 'false', readonly: slot.price === null ? 'true' : 'false' };
    for (const name of ['contextmenu', 'pointerdown', 'keydown']) handler(node, name)(event(dataset, { key: 'Enter', button: 0 }));
    t.mock.timers.tick(500);
    assert.equal(instance._pickerBar, null);
    handler(node, 'click')(event(dataset));
    assert.equal(instance._solarTooltip.index, index);
  });
});

for (const name of ['click', 'keydown']) test(`PV picker rejects an expired hour on ${name} without rerendering`, () => {
  let now = '2026-10-25T00:59:59+02:00';
  const templates = [], instance = card({ now: () => now, templates });
  const charts = chartsFor([{ date: '2026-10-25', hour: 0, price: 1 }]);
  instance._openPicker('solar-2026-10-25', 0);
  instance._renderSolarChart(charts.days[0], charts, 'Europe/Vienna');
  const button = nodes(templates, 'plan-picker-btn')[0];
  assert.ok(button);
  now = '2026-10-25T01:00:01+02:00';
  handler(button, name)(event({}, { key: 'Enter' }));
  assert.equal(instance._pickerBar, null);
  assert.equal(instance._pickerHideTimer, null);
  assert.equal(Object.keys(instance._pendingPlanActions).length, 0);
});

test('Price picker uses shared editing events and rejects missing-price entries', () => {
  const templates = [], instance = card({ templates });
  const plan = [{ date: '2026-10-25', hour: 3, price: -2, action: 'charge' }, { date: '2026-10-25', hour: 4, price: null }];
  const rendered = instance._renderPriceChart(plan);
  assert.equal(nodes(templates, 'plan-bar-group').length, 1);
  assert.equal((rendered.match(/class="plan-price-bar"/g) || []).length, 1);
  handler(nodes(templates, 'plan-bar-group')[0], 'keydown')(event({}, { key: ' ' }));
  assert.equal(instance._pickerBar.index, 0);
  assert.match(instance._renderPriceChart(plan), /class="plan-picker"/);
  let calls = 0;
  instance.hass.callService = () => { calls++; };
  handler(nodes(templates, 'plan-picker-btn')[0], 'click')(event());
  assert.equal(calls, 1, 'entries without an absolute end remain editable');
  instance._openPicker('today', 1);
  assert.doesNotMatch(instance._renderPriceChart(plan), /class="plan-picker"/);
  instance._closePicker();
});


test('PV enrichment uses current schedule and recurring blocks, and clears a confirmed pending override', () => {
  const instance = card();
  instance._solarForecast = forecast.normalizeForecast({ usable: true, time_zone: 'UTC',
    days: [{ date: '2026-10-25', start: '2026-10-25T00:00:00Z', end: '2026-10-26T00:00:00Z' },
      { date: '2026-10-26', start: '2026-10-26T00:00:00Z', end: '2026-10-27T00:00:00Z' }],
    intervals: [{ start: '2026-10-25T00:00:00Z', end: '2026-10-25T00:30:00Z', pv_estimate: 0 }],
  });
  const plan = [{ date: '2026-10-25', hour: 2, price: 4, action: 'idle' }, { date: '2026-10-26', hour: 2, price: 5, action: 'charge' }];
  const values = { charge_hours: '2026-10-26: 02', discharge_hours: '', pv_charge_hours: '', blocked_charging_hours: '2', blocked_discharging_hours: '' };
  instance._val = (_, key) => values[key];
  instance._state = () => ({ attributes: { plan } });
  instance._pendingPlanActions['2026-10-25:2'] = { action: 'pv_charge', ts: Date.now() };
  let days;
  instance._renderSolarChart = day => { (days ||= []).push(day); return ''; };
  instance._renderSolarForecast();
  assert.ok(days[0].hours.filter(hour => hour.hour === 2).every(hour => hour.displayAction === 'pv_charge' && hour.blockedCharging));
  assert.ok(days[1].hours.filter(hour => hour.hour === 2).every(hour => hour.displayAction === 'charge' && hour.blockedCharging));
  plan[0].action = 'pv_charge';
  instance._renderSolarForecast();
  assert.equal(instance._pendingPlanActions['2026-10-25:2'], undefined);
});

for (const key of ['Escape', 'Enter']) test(`picker ${key} restores focus and timeout clears picker state`, t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const templates = [], instance = card({ templates }), plan = [{ date: '2026-10-25', hour: 2, price: 1 }];
  instance._renderPriceChart(plan);
  let focused = 0;
  handler(nodes(templates, 'plan-bar-group')[0], 'keydown')(event({}, { key: 'Enter', currentTarget: { dataset: {}, focus() { focused++; } } }));
  instance._renderPriceChart(plan);
  instance.renderRoot = { activeElement: { closest: selector => selector === '.plan-picker' ? {} : null } };
  instance.hass.callService = () => {};
  handler(nodes(templates, 'plan-picker-btn')[0], 'keydown')(event({}, { key }));
  assert.equal(focused, 1);
  assert.equal(instance._pickerBar, null);
  instance._openPicker('today', 0);
  t.mock.timers.tick(15000);
  assert.equal(instance._pickerBar, null);
  assert.equal(instance._pickerHideTimer, null);
});

test('picker timeout preserves focus after the user tabs elsewhere', t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const instance = card();
  let focused = 0;
  instance._onBarKeyDown(event({}, { key: 'Enter', currentTarget: { dataset: {}, focus() { focused++; } } }), 'today', 0);
  instance.renderRoot = { activeElement: { closest: () => null } };
  t.mock.timers.tick(15000);
  assert.equal(focused, 0);
  assert.equal(instance._pickerBar, null);
  assert.equal(instance._pickerTrigger, null);
  assert.equal(instance._pickerHideTimer, null);
});

function gridConsumerCard(state, templates = [], mode = 'auto') {
  const instance = card({ templates });
  instance.config = { entity_prefix: 'victron_charge_control' };
  instance._state = (domain, key) => domain === 'switch' && key === 'grid_consumer' ? state : undefined;
  instance._val = (domain, key) => key === 'control_mode' ? mode : instance._state(domain, key)?.state;
  return instance;
}

for (const [name, state, explanation] of [
  ['missing switch', undefined, /Configure a Grid consumer power sensor/],
  ['unconfigured source', { state: 'off', attributes: { source_entity: null } }, /Configure a Grid consumer power sensor/],
  ['unavailable switch', { state: 'unavailable', attributes: { source_entity: 'sensor.ev' } }, /switch is unavailable/],
  ['unknown switch', { state: 'unknown', attributes: { source_entity: 'sensor.ev' } }, /switch is unavailable/],
]) test(`Grid Consumer explains ${name} on hover and gates its disabled handler`, () => {
  const templates = [], instance = gridConsumerCard(state, templates);
  const rendered = instance._renderGridConsumer();
  assert.match(rendered, explanation);
  assert.doesNotMatch(rendered, /role="status"/);
  const toggle = nodes(templates, 'control-row toggle-row')[0];
  assert.ok(toggle.values.some((value, index) => toggle.strings[index].endsWith('title=') && explanation.test(value)));
  assert.match(toggle.rendered, /tabindex=0/);
  assert.match(toggle.rendered, /aria-label=Grid Consumer/);
  assert.match(toggle.rendered, /\.disabled=true/);
  handler(toggle, 'change')(); // Programmatic change events must also respect disabled state.
});

for (const state of ['on', 'off']) test(`Grid Consumer ${state} uses the existing switch service wiring`, () => {
  const templates = [], instance = gridConsumerCard({ state, attributes: { source_entity: 'sensor.ev', power_w: 3000 } }, templates);
  const calls = [];
  instance.hass.callService = (...args) => calls.push(args);
  instance._renderGridConsumer();
  const toggle = nodes(templates, 'control-row toggle-row')[0];
  assert.match(toggle.rendered, /\.disabled=false/);
  assert.doesNotMatch(toggle.rendered, /tabindex=0|Configure a Grid consumer power sensor|switch is unavailable/);
  assert.match(toggle.rendered, new RegExp(`\\.checked=${state === 'on'}`));
  handler(toggle, 'change')();
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], 'switch');
  assert.equal(calls[0][1], state === 'on' ? 'turn_off' : 'turn_on');
  assert.equal(calls[0][2].entity_id, 'switch.victron_charge_control_grid_consumer');
});

for (const state of ['on', 'off']) test(`Grid Consumer invalid power warning follows ${state} state without disabling`, () => {
  const templates = [], instance = gridConsumerCard({ state, attributes: { source_entity: 'sensor.ev', power_w: null } }, templates);
  const rendered = instance._renderGridConsumer();
  assert.match(rendered, /\.disabled=false/);
  if (state === 'on') assert.match(rendered, /invalid or unavailable; zero offset/);
  else assert.doesNotMatch(rendered, /zero offset/);
});

test('Grid Consumer accepts a valid zero reading without a warning', () => {
  const instance = gridConsumerCard({ state: 'on', attributes: { source_entity: 'sensor.ev', power_w: 0 } });
  assert.doesNotMatch(instance._renderGridConsumer(), /zero offset|invalid or unavailable/);
});

for (const mode of ['off', 'auto', 'manual', 'force_charge', 'force_discharge']) test(`Grid Consumer stays under Auto Mode in ${mode}`, () => {
  const instance = gridConsumerCard({ state: 'off', attributes: { source_entity: 'sensor.ev', power_w: 0 } }, [], mode);
  const rendered = instance._renderControlsView();
  assert.match(rendered, /Grid Consumer/);
  assert.ok(rendered.indexOf('Auto Mode') < rendered.indexOf('aria-label=Grid Consumer'));
  assert.ok(rendered.indexOf('aria-label=Grid Consumer') < rendered.indexOf('Grid Feed-in'));
});

test('Grid Consumer help label opens its accessible topic with limits, timing and energy caveats', () => {
  const templates = [], instance = gridConsumerCard(undefined, templates);
  instance._openHelp = (topic, trigger) => {
    instance._helpOpen = true;
    instance._helpTopic = topic;
    instance._helpTrigger = trigger;
  };
  instance._renderGridConsumer();
  const label = templates.find(node => node.rendered.includes('aria-label=Help for Grid Consumer'));
  assert.match(label.rendered, /aria-haspopup="dialog"/);
  const trigger = {};
  handler(label, 'click')({ currentTarget: trigger });
  assert.equal(instance._helpTopic.key, 'grid_consumer');
  assert.equal(instance._helpTrigger, trigger);
  const rendered = instance._renderHelpDialog('controls', 'Settings');
  assert.match(rendered, /role="dialog" aria-modal="true" aria-label=Grid Consumer/);
  for (const text of ['Auto, Manual, Force Charge and Force Discharge', 'before grid and reduced feed-in limits',
    '5000 W', '1000 W before limits', 'five-second window', 'further changes do not restart',
    'Initial enable, restart restore and recovery', 'watt deadband', 'clears the offset without delay',
    'intentional battery discharge', 'included in ESS consumption', 'aggregate power sensor']) {
    assert.ok(rendered.includes(text), text);
  }
});

test('Overview shows the setpoint above its signed calculation without a duplicate action', () => {
  const instance = card();
  instance._state = (domain, key) => key === 'target_setpoint' ? {
    state: '-450', attributes: { calculation: {
      setting_w: 50, pv_charge_w: 1000, surplus_w: -2000, grid_consumer_w: 500, limits_w: 0,
    } },
  } : key === 'grid_consumer' ? { state: 'on', attributes: { source_entity: 'sensor.ev_power' } } : undefined;
  instance._val = (domain, key) => key === 'desired_action' ? 'pv_charge' : undefined;
  const rendered = instance._renderOverviewView();
  for (const label of ['Setting', 'PV charge', 'Surplus', 'Grid consumer', 'Grid setpoint']) {
    assert.ok(rendered.includes(label), label);
  }
  assert.match(rendered, /\+50 W/);
  assert.match(rendered, /−2,000 W/);
  assert.match(rendered, /<strong>−450 W<\/strong>/);
  assert.doesNotMatch(rendered, /<dt>Limits<\/dt>|<span>PV Charge<\/span>/);
  assert.ok(rendered.indexOf('setpoint-result') < rendered.indexOf('calculation-terms'));
});

for (const [target, setting, consumer, limit, expected] of [
  ['5000', 3000, 3000, -1000, '5,000 W (6,000 W)'],
  ['-500', -3000, 500, 2000, '−500 W (−2,500 W)'],
]) test(`capped setpoint ${target} shows the uncapped calculation in brackets`, () => {
  const instance = card();
  instance._state = () => ({ state: target, attributes: { calculation: {
    setting_w: setting, pv_charge_w: 0, surplus_w: 0, grid_consumer_w: consumer, limits_w: limit,
  } } });
  const rendered = instance._renderSetpointCalculation();
  assert.doesNotMatch(rendered, /<dt>Limits<\/dt>/);
  assert.ok(rendered.includes(`<strong>${expected}</strong>`));
});

for (const state of [undefined, 'unavailable', 'unknown', '', ' ', null, 'NaN', '0']) {
  test(`setpoint calculation handles missing data with state ${state}`, () => {
    const instance = card();
    instance._state = () => state === undefined ? undefined : { state, attributes: {} };
    const rendered = instance._renderSetpointCalculation();
    assert.match(rendered, /Calculation unavailable/);
    assert.ok(rendered.includes(state === '0' ? '<strong>0 W</strong>' : '<strong>—</strong>'));
    assert.doesNotMatch(rendered, /NaN W|undefined W/);
  });
}

function pricedPeriods(start = '2026-10-25T02:00:00+02:00', count = 8) {
  return Array.from({ length: count }, (_, index) => ({
    start_time: new Date(Date.parse(start) + index * 900000).toISOString(),
    end_time: new Date(Date.parse(start) + (index + 1) * 900000).toISOString(),
    date: '2026-10-25', hour: 2, minute: index % 4 * 15, price: index - 2,
    action: ['idle', 'charge', 'pv_charge', 'discharge'][index % 4],
  }));
}
function published(instance, plan, extra = {}) {
  instance._state = (_, key) => key === 'charge_plan' ? { attributes: { plan, time_zone: 'Europe/Vienna', ...extra } } : undefined;
}

test('Price quarters have separate actions, HA-zone offset labels, half-open current/past markers and gaps', t => {
  const browserZone = process.env.TZ;
  process.env.TZ = 'Pacific/Honolulu';
  t.after(() => { if (browserZone === undefined) delete process.env.TZ; else process.env.TZ = browserZone; });
  const templates = [], instance = card({ now: '2026-10-25T02:15:00+02:00', templates });
  const plan = pricedPeriods();
  plan[2].price = null;
  published(instance, plan);
  const rendered = instance._renderPriceChart(instance._enrichPlanDisplayState(plan));
  const bars = nodes(templates, 'plan-bar-group');
  assert.equal(bars.length, 7);
  assert.match(bars[0].rendered, /data-past=true/);
  assert.match(bars[1].rendered, /data-past=false/);
  assert.match(bars[0].rendered, /02:00 GMT\+2–02:15 GMT\+2/);
  assert.match(bars[3].rendered, /02:00 GMT\+1–02:15 GMT\+1/);
  assert.match(rendered, /fill="var\(--vcc-success/);
  assert.match(rendered, /fill="#ff6600"/);
  const markers = templates.filter(node => node.strings.join('').includes('stroke-dasharray="4,3"'));
  assert.equal(markers.length, 1);
  handler(bars[0], 'keydown')(event({ past: 'true' }, { key: 'Enter' }));
  assert.equal(instance._pickerBar, null);
  instance._openPicker('today', 2);
  assert.doesNotMatch(instance._renderPriceChart(plan), /class="plan-picker"/);
  instance._closePicker();
});

for (const view of ['price', 'pv']) test(`${view} repeated DST quarters send exact instant payloads and reconcile only that period`, t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const templates = [], instance = card({ now: '2026-10-25T01:00:00+02:00', templates });
  const plan = pricedPeriods();
  published(instance, plan);
  const render = () => {
    const enriched = instance._enrichPlanDisplayState(plan);
    if (view === 'price') instance._renderPriceChart(enriched);
    else {
      const charts = chartsFor(enriched);
      instance._renderSolarChart(charts.days[0], charts, 'Europe/Vienna');
      return charts.days[0];
    }
  };
  const day = render();
  const chartId = view === 'price' ? 'today' : 'solar-2026-10-25';
  const index = view === 'price' ? 5 : day.hours.findIndex(period => period.start_time === plan[5].start_time);
  const targetNode = view === 'price' ? nodes(templates, 'plan-bar-group')[index]
    : nodes(templates, 'solar-slot')[day.slots.findIndex(slot => slot.hourIndex === index)];
  handler(targetNode, 'keydown')(event({}, { key: 'Enter' }));
  assert.equal(instance._pickerBar.startTime, plan[5].start_time);
  render();
  let payload;
  instance.hass.callService = (domain, service, data) => { assert.equal(service, 'set_slot_action'); payload = data; return Promise.resolve(); };
  handler(nodes(templates, 'plan-picker-btn').find(node => node.rendered.includes('data-action=discharge ')), 'click')(event());
  assert.equal(JSON.stringify(payload), JSON.stringify({ start_time: plan[5].start_time, action: 'discharge' }));
  let display = instance._enrichPlanDisplayState(plan);
  assert.equal(display[5].displayAction, 'discharge');
  assert.equal(display[1].displayAction, 'charge', 'other occurrence and sibling quarters keep their actions');
  plan[5] = { ...plan[5], action: 'discharge', start_time: '2026-10-25T02:15:00+01:00' };
  display = instance._enrichPlanDisplayState(plan);
  assert.equal(display[5].displayAction, 'discharge');
  assert.equal(instance._pendingPlanActions[String(Date.parse(plan[5].start_time))], undefined);
  assert.equal(instance._pickerBar, null);
  // Touch hold selects a separate exact period too.
  handler(targetNode, 'pointerdown')(event({}, { button: 0, clientX: 20, clientY: 50 }));
  t.mock.timers.tick(500);
  assert.equal(instance._pickerBar.chartId, chartId);
  assert.equal(Date.parse(instance._pickerBar.startTime), Date.parse(plan[5].start_time));
  instance._closePicker();
});

test('open picker retains timestamp identity when a plan update inserts an earlier period', () => {
  const templates = [], instance = card({ templates }), plan = pricedPeriods();
  published(instance, plan);
  instance._renderPriceChart(plan);
  instance._openPicker('today', 1);
  const earlier = { ...plan[0], start_time: '2026-10-24T23:45:00Z', end_time: plan[0].start_time };
  templates.length = 0;
  instance._renderPriceChart([earlier, ...plan]);
  let payload;
  instance.hass.callService = (_, service, data) => { assert.equal(service, 'set_slot_action'); payload = data; };
  handler(nodes(templates, 'plan-picker-btn')[0], 'click')(event());
  assert.equal(payload.start_time, plan[1].start_time);
});

test('structured actions beat compact schedule states; structured arrays support plans without actions', () => {
  const instance = card(), plan = pricedPeriods();
  const values = { charge_hours: '2026-10-25:2', discharge_hours: '2026-10-25:2', pv_charge_hours: '2026-10-25:2' };
  instance._val = (_, key) => values[key];
  published(instance, plan, { charge_hours: [plan[0]], discharge_hours: [plan[1]], pv_charge_hours: [plan[3]] });
  assert.deepEqual(Array.from(instance._enrichPlanDisplayState(plan), period => period.displayAction), plan.map(period => period.action));
  const withoutActions = plan.map(({ action, ...period }) => period);
  assert.deepEqual(Array.from(instance._enrichPlanDisplayState(withoutActions), period => period.displayAction).slice(0, 4), ['charge', 'discharge', 'idle', 'pv_charge']);
});

test('mixed price/PV charts provide at least 28px per quarter and preserve full hourly bars', () => {
  const templates = [], instance = card({ templates });
  const plan = pricedPeriods('2026-10-25T00:00:00+02:00', 4);
  plan.push({ ...plan[0], start_time: plan.at(-1).end_time, end_time: '2026-10-26T00:00:00+01:00', price: 5 });
  published(instance, plan);
  const price = instance._renderPriceChart(plan);
  assert.match(price, /min-width:2890px/);
  const hitWidths = [...price.matchAll(/class="plan-bar-hit"\s+x="[^"]+" y="[^"]+" width="([^"]+)"/g)].map(match => Number(match[1]));
  assert.ok(hitWidths.every(width => width >= 28));
  assert.equal(hitWidths.at(-1), 24 * 4 * 28);
  const charts = chartsFor(plan), pv = instance._renderSolarChart(charts.days[0], charts, 'Europe/Vienna');
  assert.match(pv, /min-width:2900px/);
  assert.equal(charts.days[0].hours.length, 5, 'long published interval remains one bar');
});

for (const view of ['price', 'pv']) test(`${view} exact-period picker rechecks expiry before sending`, () => {
  let now = '2026-10-25T02:14:59+02:00';
  const templates = [], instance = card({ now: () => now, templates }), plan = pricedPeriods();
  published(instance, plan);
  if (view === 'price') { instance._renderPriceChart(plan); instance._openPicker('today', 0); instance._renderPriceChart(plan); }
  else {
    const charts = chartsFor(plan), day = charts.days[0];
    instance._renderSolarChart(day, charts, 'Europe/Vienna');
    instance._openPicker('solar-2026-10-25', day.hours.findIndex(period => period.start_time === plan[0].start_time));
    instance._renderSolarChart(day, charts, 'Europe/Vienna');
  }
  now = '2026-10-25T02:15:00+02:00';
  handler(nodes(templates, 'plan-picker-btn')[0], 'keydown')(event({}, { key: 'Enter' }));
  assert.equal(Object.keys(instance._pendingPlanActions).length, 0);
  assert.equal(instance._pickerBar, null);
});

test('duration sliders consume quarter-hour backend steps and keep hourly recurring chips', () => {
  const templates = [], instance = card({ templates });
  instance._state = (_, key) => key === 'cheapest_hours_auto_charge' ? { state: '1.25', attributes: { min: 0, max: 24, step: .25 } } : undefined;
  const rendered = instance._renderControlsView();
  assert.match(rendered, /aria-label=Charge Duration/);
  assert.match(rendered, /step=0.25/);
  assert.match(rendered, /1.25 h/);
  assert.equal((instance._renderHourChips({ selected: [], onClick() {} }).match(/class="hour-chip /g) || []).length, 24);
});

test('exact-period service failure rolls back its edit without discarding a newer choice', async () => {
  const instance = card(), plan = pricedPeriods();
  published(instance, plan);
  const failures = [];
  instance.hass.callService = () => new Promise((_, reject) => failures.push(reject));
  const entry = instance._enrichPlanDisplayState(plan)[0], key = String(Date.parse(entry.start_time));
  instance._setPlanSlotAction(entry, 'charge');
  instance._setPlanSlotAction(entry, 'discharge');
  failures[0](new Error('First edit failed'));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(instance._pendingPlanActions[key].action, 'discharge');
  failures[1](new Error('Second edit failed'));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(instance._pendingPlanActions[key], undefined);
  assert.equal(instance._enrichPlanDisplayState(plan)[0].displayAction, 'idle');
});

for (const preliminary of ['focus', 'mouseenter']) test(`Price click retains a tooltip already shown by ${preliminary}`, t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const templates = [], instance = card({ templates }), plan = pricedPeriods();
  published(instance, plan);
  instance._renderPriceChart(plan);
  const bar = nodes(templates, 'plan-bar-group')[1];
  handler(bar, preliminary)(event());
  handler(bar, 'click')(event());
  assert.equal(instance._tooltipBar?.chartId, 'today');
  assert.equal(instance._tooltipBar?.index, 1);
  assert.match(instance._renderPriceChart(plan), /class="plan-bar-tooltip" pointer-events="none"/);
  t.mock.timers.tick(9000);
  handler(bar, 'click')(event());
  t.mock.timers.tick(9000);
  assert.equal(instance._tooltipBar?.index, 1, 'another click retains the tooltip and refreshes its timeout');
  t.mock.timers.tick(1000);
  assert.equal(instance._tooltipBar, null);
  assert.equal(instance._tooltipHideTimer, null);
});

test('History retains click-to-toggle tooltips', t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const instance = card();
  instance._onBarClick(event(), 'history', 0);
  assert.equal(instance._tooltipBar?.index, 0);
  instance._onBarClick(event(), 'history', 0);
  assert.equal(instance._tooltipBar, null);
  assert.equal(instance._tooltipHideTimer, null);
});

for (const view of ['price', 'pv']) for (const gesture of ['contextmenu', 'pointerdown', 'keydown']) {
  for (const edge of ['left', 'right']) for (const scale of [.75, 1.25]) {
    test(`${view} ${gesture} picker stays inside the scrolled ${edge} edge at SVG scale ${scale}`, t => {
      t.mock.timers.enable({ apis: ['setTimeout'] });
      const templates = [], instance = card({ now: '2026-10-24T00:00:00Z', templates });
      const plan = pricedPeriods('2026-10-25T00:00:00+02:00', 100);
      published(instance, plan);
      const charts = chartsFor(plan), day = charts.days[0], index = 20;
      const viewport = { left: 40, right: 350, top: 100 };
      const clientX = edge === 'left' ? viewport.left + 5 : viewport.right - 5;
      const barCenter = 50 + index * 28 + 14;
      const scrollLeft = barCenter - (clientX - viewport.left) / scale;
      assert.ok(scrollLeft > 0);
      const svgEl = {
        closest: selector => selector === '.plan-chart-scroll' ? { getBoundingClientRect: () => viewport } : null,
        getScreenCTM: () => ({ inverse: () => ({ scale, tx: viewport.left - scrollLeft * scale, ty: viewport.top }) }),
        createSVGPoint: () => ({ x: 0, y: 0, matrixTransform(matrix) {
          return { x: (this.x - matrix.tx) / matrix.scale, y: (this.y - matrix.ty) / matrix.scale };
        } }),
      };
      const render = () => view === 'price' ? instance._renderPriceChart(plan) : instance._renderSolarChart(day, charts, 'Europe/Vienna');
      render();
      const node = view === 'price' ? nodes(templates, 'plan-bar-group')[index]
        : nodes(templates, 'solar-slot')[day.slots.findIndex(slot => slot.hourIndex === index)];
      const currentTarget = { dataset: {}, closest: selector => selector === 'svg' ? svgEl : null, focus() {} };
      handler(node, gesture)(event({}, { currentTarget, clientX, clientY: 180, button: 0, key: 'Enter' }));
      if (gesture === 'pointerdown') t.mock.timers.tick(500);
      assert.ok(instance._pickerBar);
      if (gesture === 'keydown') assert.equal(instance._pickerBar.anchorX, null, 'keyboard positions from the selected bar without a pointer anchor');
      templates.length = 0;
      render();
      const picker = nodes(templates, 'plan-picker')[0];
      assert.ok(picker);
      const rects = [picker, ...nodes(templates, 'plan-picker-btn')].map(item => {
        const [, x, , width] = item.rendered.match(/<rect x="([^"]+)" y="([^"]+)" width="([^"]+)"/);
        return { left: viewport.left + (Number(x) - scrollLeft) * scale, right: viewport.left + (Number(x) + Number(width) - scrollLeft) * scale };
      });
      assert.equal(rects.length, 5, 'picker and all four action buttons are measured');
      for (const rect of rects) {
        assert.ok(rect.left >= viewport.left - 1e-7, `left ${rect.left} stays within ${viewport.left}`);
        assert.ok(rect.right <= viewport.right + 1e-7, `right ${rect.right} stays within ${viewport.right}`);
      }
      instance._closePicker();
    });
  }
}

for (const commit of [true, false]) test(`threshold drag preserves Lit label nodes on ${commit ? 'commit' : 'cancel'}`, t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const instance = card(), calls = [];
  instance.setConfig({ entity_prefix: 'garage' });
  instance.hass.callService = (...args) => { calls.push(args); return Promise.resolve(); };
  instance.classList = { add() {}, remove() {} };
  instance._addThresholdDragListeners = () => {};
  instance._removeThresholdDragListeners = () => {};
  instance._clientToSvgY = y => y;
  const marker = { nodeType: 8, nodeValue: '?lit$marker$' }, textNode = { nodeType: 3, nodeValue: '10' };
  const positions = {}, label = {
    childNodes: [marker, textNode], lastChild: textNode,
    setAttribute: (key, value) => { positions[key] = value; },
    set textContent(_) { assert.fail('Replacing label content removes the Lit marker needed for the next render'); },
  };
  const lines = [{ setAttribute() {} }, { setAttribute() {} }];
  const group = { classList: { add() {}, remove() {} }, closest: () => ({}), querySelectorAll: () => lines, querySelector: () => label };
  const scale = { scaleMin: 0, scaleMax: 40, scaleRange: 40, padT: 38, plotH: 202, step: .25 };
  instance._onThresholdPointerDown(event({}, { currentTarget: group }), 'charge', scale);
  instance._onThresholdPointerMove(event({}, { clientY: 118.8 }));
  assert.equal(textNode.nodeValue, '10', 'a drag before hold unlocks leaves the label unchanged');
  t.mock.timers.tick(1000);
  instance._onThresholdPointerMove(event({}, { clientY: 118.8 }));
  assert.equal(textNode.nodeValue, '24');
  assert.equal(label.childNodes[0], marker);
  assert.equal(label.childNodes[1], textNode);
  assert.equal(marker.nodeValue, '?lit$marker$');
  assert.ok(Math.abs(positions.y - 122.3) < 1e-7);
  if (commit) instance._onThresholdPointerUp(event());
  else instance._finishThresholdDrag(false);
  assert.equal(instance._thresholdDrag, null);
  assert.equal(JSON.stringify(calls), JSON.stringify(commit ? [['number', 'set_value', { entity_id: 'number.garage_charge_price_threshold', value: 24 }]] : []));
  assert.equal(instance._pendingThresholds.charge, commit ? 24 : undefined);
});
