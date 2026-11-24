import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import * as forecast from '../src/solar-forecast.mjs';
import { normalizeView } from '../src/view.mjs';

const source = readFileSync(new URL('../src/victron-charge-controller-card.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/registerCard\(\);\s*$/, 'globalThis.Card = VictronChargeControllerCard;');
const template = (strings, ...values) => strings.reduce((text, string, index) => text + string + (values[index] ?? ''), '');

function setup() {
  let now = Date.parse('2026-10-15T00:59:30Z'), nextTimer = 0;
  const timers = new Map(), listeners = new Map(), requests = [];
  const document = {
    hidden: false,
    addEventListener: (name, callback) => listeners.set(name, callback),
    removeEventListener: name => listeners.delete(name),
  };
  const context = vm.createContext({
    ...forecast, normalizeView, html: template, svg: template, css: template, nothing: '', document,
    window: { addEventListener() {}, removeEventListener() {} },
    LitElement: class {
      requestUpdate(...args) { requests.push(args); }
      connectedCallback() {}
      disconnectedCallback() {}
    },
    Date: class extends Date { static now() { return now; } },
    setTimeout: (callback, delay) => { timers.set(++nextTimer, { callback, at: now + delay }); return nextTimer; },
    clearTimeout: id => timers.delete(id),
  });
  vm.runInContext(source, context);
  const card = new context.Card();
  card.setConfig({ view: 'plan', entity_prefix: 'garage' });
  card.hass = { states: {
    'select.garage_control_mode': { state: 'auto' },
    'sensor.garage_last_schedule_update': { state: new Date(now).toISOString() },
  }, config: { time_zone: 'UTC' } };
  const pollerCalls = [];
  card._forecastPoller.setActive = (...args) => pollerCalls.push(args);
  const flush = () => { const rendered = card.render(); card.updated(); return rendered; };
  const connect = () => { card.isConnected = true; card.connectedCallback(); flush(); };
  const visibility = hidden => { document.hidden = hidden; listeners.get('visibilitychange')(); };
  const advance = milliseconds => {
    const target = now + milliseconds;
    while (true) {
      const next = [...timers].filter(([, timer]) => timer.at <= target).sort((a, b) => a[1].at - b[1].at)[0];
      if (!next) break;
      timers.delete(next[0]); now = next[1].at; next[1].callback();
    }
    now = target;
  };
  const push = (states, context = {}) => { card.hass = { ...card.hass, states, ...context }; };
  requests.length = 0;
  return { card, requests, timers, document, connect, visibility, advance, flush, push, pollerCalls, now: () => now };
}

test('Plan stores every hass object but only integration entity identities and context request an update', () => {
  const { card, requests, push } = setup();
  const original = card.hass.states;
  push({ ...original, 'sensor.unrelated': { state: '1' } });
  assert.equal(requests.length, 0);
  const latest = card.hass;
  assert.equal(latest.states['sensor.unrelated'].state, '1');
  push({ ...latest.states, 'sensor.garage_current_price': { state: '0.2' } });
  assert.equal(requests.length, 1, 'entity addition');
  push({ ...card.hass.states, 'sensor.garage_current_price': { state: '0.2' } });
  assert.equal(requests.length, 2, 'replacement with equal content still counts');
  push(original);
  assert.equal(requests.length, 3, 'entity removal');
  push(original, { config: { time_zone: 'Europe/Vienna' } });
  assert.equal(requests.length, 4);
  const connection = { connected: true };
  push(original, { connection });
  connection.connected = false;
  push(original);
  assert.equal(requests.length, 6, 'connection identity and in-place connection status change');
  for (const key of ['locale', 'language']) push(original, { [key]: 'de' });
  assert.equal(requests.length, 8);
});

test('explicit updates survive unrelated HA assignment in either order; other views keep HA updates', () => {
  const { card, requests, push } = setup();
  card.requestUpdate();
  push({ ...card.hass.states, 'sensor.unrelated': { state: '1' } });
  assert.equal(requests.length, 1);
  push({ ...card.hass.states, 'sensor.unrelated': { state: '2' } });
  card.requestUpdate();
  assert.equal(requests.length, 2);
  for (const view of ['overview', 'settings', 'costs']) {
    card.setConfig({ ...card.config, view });
    const before = requests.length;
    push({ ...card.hass.states, 'sensor.unrelated': { state: view } });
    assert.equal(requests.length, before + 1);
  }
});

test('renamed and suffixed entities share one snapshot scan, detect replacement/removal, and reset with config', () => {
  const { card, requests, push } = setup();
  let scans = 0;
  const id = 'sensor.cellar_garage_fixed_plans_2';
  const states = new Proxy({ [id]: { state: '1' }, 'sensor.cellar_garage_charge_plan_2': { state: 'ready' } }, {
    ownKeys: target => { scans++; return Reflect.ownKeys(target); },
  });
  push(states);
  assert.equal(card._eid('sensor', 'fixed_plans'), id);
  assert.equal(card._eid('sensor', 'charge_plan'), 'sensor.cellar_garage_charge_plan_2');
  assert.equal(card._eid('number', 'charge_price_threshold'), 'number.garage_charge_price_threshold');
  card.hass = { ...card.hass };
  assert.equal(scans, 1);
  const before = requests.length;
  push({ ...states, [id]: { state: '2' } });
  assert.equal(requests.length, before + 1);
  push({ 'sensor.garage_fixed_plans_3': { state: '3' } });
  assert.equal(card._eid('sensor', 'fixed_plans'), 'sensor.garage_fixed_plans_3');
  push({ ...card.hass.states, 'sensor.garage_fixed_plans_2': { state: '2' } });
  assert.equal(card._eid('sensor', 'fixed_plans'), 'sensor.garage_fixed_plans_2', 'new preferred alias replaces cached alias');
  card.setConfig({ view: 'plan', entity_prefix: 'shed' });
  push({ 'sensor.shed_fixed_plans_2': { state: '4' } });
  assert.equal(card._eid('sensor', 'fixed_plans'), 'sensor.shed_fixed_plans_2');
  assert.deepEqual(Object.keys(card._entityAliases), ['sensor.shed_fixed_plans']);
});

test('visible Plan refreshes at the next minute, suspends hidden/disconnected, and restores immediately', () => {
  const { card, requests, timers, connect, visibility, advance, flush, pollerCalls } = setup();
  connect();
  assert.equal(timers.size, 1);
  const timer = card._planRefreshTimer;
  flush(); flush();
  assert.equal(card._planRefreshTimer, timer, 'repeated updates keep one minute timer');
  requests.length = 0;
  advance(29999);
  assert.equal(requests.length, 0);
  advance(1);
  assert.equal(requests.length, 1);
  flush();
  assert.equal(timers.size, 1);
  visibility(true);
  assert.equal(timers.size, 0);
  assert.equal(pollerCalls.at(-1)[0], false);
  advance(120000);
  requests.length = 0;
  visibility(false);
  assert.equal(requests.length, 1, 'visibility restoration requests current styling immediately');
  assert.equal(pollerCalls.at(-1)[0], true);
  assert.equal(timers.size, 1);
  card.isConnected = false;
  card.disconnectedCallback();
  assert.equal(timers.size, 0);
  connect();
  assert.equal(timers.size, 1);
  card.setConfig({ view: 'settings' }); flush();
  assert.equal(timers.size, 0);
});

test('pending actions, fixed hours, names and activation expire at their own ten-second deadlines without HA', () => {
  const { card, timers, connect, advance, flush, now } = setup();
  connect();
  card._pendingPlanActions.first = { action: 'charge', ts: now() };
  card._pendingFixedPlanNames[1] = { value: 'Evening', ts: now() };
  card._pendingFixedPlanHours[1] = { 3: { action: 'charge', ts: now() } };
  card._pendingActiveFixedPlan = { value: 1, ts: now() };
  card._pendingThresholds.charge = { value: 8 };
  flush();
  advance(4000);
  card._pendingPlanActions.second = { action: 'discharge', ts: now() };
  flush();
  advance(5999);
  assert.ok(card._pendingPlanActions.first);
  advance(1);
  assert.equal(card._pendingPlanActions.first, undefined);
  assert.ok(card._pendingPlanActions.second);
  assert.equal(Object.keys(card._pendingFixedPlanNames).length, 0);
  assert.equal(Object.keys(card._pendingFixedPlanHours).length, 0);
  assert.equal(card._pendingActiveFixedPlan, undefined);
  assert.equal(card._pendingThresholds.charge.value, 8, 'threshold pending semantics stay separate');
  flush(); advance(4000); flush();
  assert.equal(Object.keys(card._pendingPlanActions).length, 0);
  assert.equal(timers.size, 1, 'only the minute timer remains');
});

for (const pause of ['hidden', 'disconnected']) test(`pending edits expire on return after ${pause}`, () => {
  const { card, timers, connect, visibility, advance, flush, now } = setup();
  connect();
  card._pendingPlanActions.hour = { action: 'charge', ts: now() };
  flush();
  if (pause === 'hidden') visibility(true);
  else { card.isConnected = false; card.disconnectedCallback(); }
  assert.equal(timers.size, 0);
  advance(11000);
  if (pause === 'hidden') { visibility(false); flush(); }
  else connect();
  assert.equal(Object.keys(card._pendingPlanActions).length, 0);
  assert.equal(timers.size, 1);
});

test('minute refresh updates current/past periods and schedule age without a state push', () => {
  const { card, connect, push, advance, flush } = setup();
  push({ ...card.hass.states, 'sensor.garage_charge_plan': { state: 'ready', attributes: { plan: [
    { date: '2026-10-15', hour: 0, minute: 45, start_time: '2026-10-15T00:45:00Z', end_time: '2026-10-15T01:00:00Z', price: -3, action: 'charge' },
    { date: '2026-10-15', hour: 1, start_time: '2026-10-15T01:00:00Z', end_time: '2026-10-15T01:15:00Z', price: 2, action: 'idle' },
  ] } } });
  connect();
  const before = flush();
  assert.match(before, /Updated: just now/);
  assert.match(before, /class="plan-axis-label plan-current-hour"\s*>00</);
  advance(90000);
  const after = flush();
  assert.match(after, /Updated: 1 min ago/);
  assert.match(after, /class="plan-axis-label plan-current-hour"\s*>01</);
  assert.match(after, /data-past=true/);
});

test('chart arrays contain only this render and release obsolete dates, modes, views, config and disconnect', () => {
  const { card, push, flush } = setup();
  const makeForecast = day => forecast.normalizeForecast({ usable: true, time_zone: 'UTC',
    days: [0, 1].map(offset => ({ date: `2026-10-${day + offset}`, start: `2026-10-${day + offset}T00:00:00Z`, end: `2026-10-${day + offset + 1}T00:00:00Z` })),
    intervals: [{ start: `2026-10-${day}T00:00:00Z`, end: `2026-10-${day}T01:00:00Z`, pv_estimate: 1 }],
  });
  card._solarForecast = makeForecast(15);
  card._setPlanChartMode('pv'); card.render();
  assert.deepEqual(Object.keys(card._chartPeriods), ['solar-2026-10-15', 'solar-2026-10-16']);
  card._solarForecast = makeForecast(16); card.render();
  assert.deepEqual(Object.keys(card._chartPeriods), ['solar-2026-10-16', 'solar-2026-10-17']);
  card._setPlanChartMode('price');
  assert.equal(Object.keys(card._chartPeriods).length, 0);
  const plan = [{ date: '2026-10-16', hour: 1, price: 2 }, { date: '2026-10-17', hour: 1, price: 3 }];
  push({ ...card.hass.states, 'sensor.garage_charge_plan': { state: 'ready', attributes: { plan } } });
  card.render();
  assert.deepEqual(Object.keys(card._chartPeriods), ['today', 'tomorrow']);
  push({ ...card.hass.states, 'sensor.garage_charge_plan': { state: 'ready', attributes: { plan: [plan[0]] } } });
  card.render();
  assert.deepEqual(Object.keys(card._chartPeriods), ['today']);
  card._openPlanPage(1);
  assert.equal(Object.keys(card._chartPeriods).length, 0, 'page navigation clears references before its render');
  card._chartPeriods.stale = plan;
  card._openNewFixedPlan({ 1: {} });
  assert.equal(Object.keys(card._chartPeriods).length, 0, 'new fixed-plan navigation also clears chart references');
  card.render();
  assert.equal(Object.keys(card._chartPeriods).length, 0);
  card._chartPeriods.stale = plan;
  card.setConfig({ view: 'settings' });
  assert.equal(Object.keys(card._chartPeriods).length, 0);
  card._chartPeriods.stale = plan; card.disconnectedCallback();
  assert.equal(Object.keys(card._chartPeriods).length, 0);
  card.setConfig({ view: 'plan', entity_prefix: 'garage' });
  card._planPage = 'auto'; card.isConnected = false;
  flush();
  assert.equal(Object.keys(card._chartPeriods).length, 0, 'a queued Lit update after disconnect does not retain arrays');
});

test('each chart computes hour groups once and a late source removal prevents a cached picker write', () => {
  const { card, push } = setup();
  const plan = [{ date: '2026-10-15', hour: 1, start_time: '2026-10-15T01:00:00Z', end_time: '2026-10-15T02:00:00Z', price: 2 }];
  push({ ...card.hass.states, 'sensor.garage_charge_plan': { state: 'ready', attributes: { plan } } });
  let groups = 0;
  const original = card._planHourGroups;
  card._planHourGroups = function (...args) { groups++; return original.apply(this, args); };
  card.render();
  assert.equal(groups, 1);
  const entry = card._chartPeriods.today[0];
  card._pickerBar = { chartId: 'today', group: original.call(card, [entry])[0] };
  assert.ok(card._currentPickerPeriod(entry));
  const states = { ...card.hass.states };
  delete states['sensor.garage_charge_plan'];
  push(states);
  assert.equal(card._currentPickerPeriod(entry), null, 'source is checked before the queued render');
  const start = Date.parse('2026-10-15T00:00:00Z');
  const charts = forecast.buildForecastCharts({ time_zone: 'UTC', intervals: [], days: [0, 1].map(index => ({
    date: `2026-10-${15 + index}`, start: start + index * 86400000, end: start + (index + 1) * 86400000,
  })) }, plan);
  groups = 0;
  charts.days.forEach(day => card._renderSolarChart(day, charts, 'UTC'));
  assert.equal(groups, 2, 'PV also computes each chart group once');
});

test('Settings edits each fixed price independently and rejects invalid drafts without clearing the saved rate', async () => {
  const { card, push } = setup();
  card.setConfig({ view: 'settings', entity_prefix: 'garage' });
  const buy = 'text.cellar_garage_buy_price_2';
  const sell = 'text.garage_sell_price';
  const calls = [];
  push({ ...card.hass.states, [buy]: { state: '24.75' }, [sell]: { state: '' } }, {
    callService: (domain, service, data) => calls.push([domain, service, { ...data }]),
  });
  const rendered = card.render();
  assert.match(rendered, /<label class="tariff-field">\s*<span>Buy price \(ct\/kWh\)<\/span>\s*<input type="text"[^>]*\.value=24\.75/);
  assert.doesNotMatch(rendered, /<input[^>]*inputmode="decimal"/);
  assert.match(rendered, /Sell price \(ct\/kWh\)<\/span>\s*<input[^>]*\?disabled=false placeholder=Enter fixed price/);

  const input = {
    value: '',
    setCustomValidity(message) { this.message = message; },
    setAttribute(key, value) { this[key] = value; },
    reportValidity() { this.reported = true; },
  };
  for (const value of ['-', ' ', '2,5.7', 'NaN', '0x10', '1e2']) {
    input.value = value;
    card._setTariff('buy_price', input);
    assert.equal(input.value, value);
  }
  assert.deepEqual(calls, []);
  assert.equal(input['aria-invalid'], 'true');
  assert.equal(input.reported, true);

  input.value = '0';
  await card._setTariff('buy_price', input);
  input.value = ' -2,5 ';
  await card._setTariff('sell_price', input);
  input.value = '';
  await card._setTariff('buy_price', input);
  assert.deepEqual(calls, [
    ['text', 'set_value', { entity_id: buy, value: '0' }],
    ['text', 'set_value', { entity_id: sell, value: '-2.5' }],
    ['text', 'set_value', { entity_id: buy, value: '' }],
  ]);

  for (const state of ['unknown', 'unavailable', undefined]) {
    push({ ...card.hass.states, [buy]: state === undefined ? undefined : { state } });
    assert.match(card._renderTariffField('buy_price', 'Buy price'), /\?disabled=true placeholder=Unavailable/);
    input.value = '15';
    card._setTariff('buy_price', input);
    assert.equal(input.value, '');
  }
  assert.equal(calls.length, 3);
});

test('Plan shows fixed rate lines on the shared Price scale and preserves missing spot data and controls', () => {
  const { card, push, flush } = setup();
  const buy = 'text.garage_buy_price';
  const sell = 'text.garage_sell_price';
  const chargePlan = 'sensor.garage_charge_plan';
  const today = { date: '2026-10-15', hour: 1, price: 4 };
  const tomorrow = { date: '2026-10-16', hour: 1, price: 2 };
  const states = {
    ...card.hass.states,
    [buy]: { state: '50' },
    [sell]: { state: '-10' },
    [chargePlan]: { state: 'ready', attributes: { plan: [today, tomorrow] } },
    'number.garage_charge_price_threshold': { state: '4' },
  };
  push(states);
  const rendered = flush();
  const ys = [...rendered.matchAll(/class="plan-tariff" pointer-events="none">\s*<line [^>]*y1="([^"]+)"[^>]*stroke-dasharray="4,3"/g)]
    .map(match => Number(match[1]));
  assert.equal(ys.length, 4);
  assert.deepEqual(ys.slice(0, 2), ys.slice(2));
  assert.ok(ys[0] >= 38 && ys[0] < ys[1] && ys[1] <= 250);
  assert.equal((rendered.match(/>Buy 50<\/text>/g) || []).length, 2);
  assert.equal((rendered.match(/>Sell -10<\/text>/g) || []).length, 2);
  assert.match(rendered, /class="threshold-line-group" data-type="charge"/);
  assert.match(rendered, /class="plan-bar-hit"/);

  push({ ...states, [buy]: { state: '0' }, [sell]: { state: '0.0' } });
  assert.equal((flush().match(/>Buy \/ Sell 0<\/text>/g) || []).length, 2);
  push({ ...states, [buy]: { state: 'unavailable' }, [sell]: { state: '0' } });
  assert.equal((flush().match(/>Sell 0<\/text>/g) || []).length, 2);
  push({ ...states, [buy]: { state: '0' }, [sell]: { state: '' } });
  assert.equal((flush().match(/>Buy 0<\/text>/g) || []).length, 2);

  card._solarForecast = forecast.normalizeForecast({
    usable: true, time_zone: 'UTC',
    days: [
      { date: today.date, start: '2026-10-15T00:00:00Z', end: '2026-10-16T00:00:00Z' },
      { date: tomorrow.date, start: '2026-10-16T00:00:00Z', end: '2026-10-17T00:00:00Z' },
    ],
    intervals: [{ start: '2026-10-15T00:00:00Z', end: '2026-10-15T01:00:00Z', pv_estimate: 1 }],
  });
  card._setPlanChartMode('pv');
  const solar = flush();
  assert.match(solar, /PV 10%: unavailable - PV: 1\.0 kWh/);
  assert.doesNotMatch(solar, /class="plan-tariff"/);
  card._setPlanChartMode('price');

  push({ ...states, [chargePlan]: { state: 'ready', attributes: { plan: [today, { ...tomorrow, price: null }] } } });
  assert.match(flush(), /Tomorrow — prices not yet available/);
  push({ ...states, [chargePlan]: { state: 'ready', attributes: { plan: [{ ...today, price: null }] } } });
  assert.match(flush(), /No EPEX price data available/);
  assert.doesNotMatch(flush(), /class="plan-tariff"/);
});

function directionalPlan(date = '2026-10-15') {
  const period = (minute, action, prices) => ({ date, hour: 1, minute, action, ...prices,
    start_time: `${date}T01:${String(minute).padStart(2, '0')}:00Z`,
    end_time: `${date}T${minute === 45 ? '02:00' : `01:${minute + 15}`}:00Z`,
  });
  return [
    period(0, 'charge', { price: 4, import_price: 4, export_price: -5 }),
    period(15, 'discharge', { price: 7, import_price: 10, export_price: 7 }),
    period(30, 'pv_charge', { price: 12, import_price: 0, export_price: 12 }),
    period(45, 'idle', { price: 0, import_price: null, export_price: 0 }),
  ];
}

const priceCharts = rendered => [...rendered.matchAll(/<svg class="plan-chart".*?<\/svg>/gs)].map(match => match[0]);
const axisValues = chart => [...chart.matchAll(/class="plan-axis-label">([^<]+)<\/text>/g)].map(match => Number(match[1]));
const priceBars = chart => [...chart.matchAll(/class="plan-price-bar"\s+x="([^"]+)" y="([^"]+)" width="[^"]+" height="([^"]+)"\s+fill="([^"]+)"/g)]
  .map(([, x, y, height, fill]) => ({ x: Number(x), y: Number(y), height: Number(height), fill }));

test('Formula plots align times and share scales across days by direction, with matching actions and price lines', () => {
  const { card, push, flush } = setup();
  const today = directionalPlan();
  const tomorrow = directionalPlan('2026-10-16');
  tomorrow[0] = { ...tomorrow[0], price: 17, import_price: 17, export_price: -20 };
  const states = {
    ...card.hass.states,
    'text.garage_sell_price': { state: '100' },
    'switch.garage_relative_auto_mode': { state: 'on' },
    'number.garage_charge_price_threshold': { state: '11' },
    'number.garage_discharge_price_threshold': { state: '22' },
    'sensor.garage_charge_plan': { state: 'ready', attributes: {
      price_formula_configured: true, price_reference_min: -20, price_reference_max: 17, plan: [...today, ...tomorrow],
    } },
  };
  push(states);
  const rendered = flush();
  assert.equal((rendered.match(/>Import · Charging<\/div>/g) || []).length, 2);
  assert.equal((rendered.match(/>Export · Discharging<\/div>/g) || []).length, 2);
  const charts = priceCharts(rendered);
  assert.equal(charts.length, 4);
  const [buy, sell, buyTomorrow, sellTomorrow] = charts;
  assert.ok(charts.every(chart => chart.includes('ct/kWh')));
  assert.deepEqual(axisValues(buy), axisValues(buyTomorrow));
  assert.deepEqual(axisValues(sell), axisValues(sellTomorrow));
  assert.ok(Math.max(...axisValues(buy)) >= 17 && Math.max(...axisValues(buy)) < 20);
  assert.equal(Math.min(...axisValues(sell)), -20);
  assert.ok(Math.max(...axisValues(sell)) >= 100);
  assert.match(sell, />Sell accounting 100<\/text>/);
  assert.doesNotMatch(buy, /class="plan-tariff"/);
  assert.match(buy, /data-type="charge"[\s\S]*class="plan-threshold-label"[^>]*>6<\/text>/);
  assert.match(sell, /data-type="discharge"[\s\S]*class="plan-threshold-label"[^>]*>2<\/text>/);
  assert.doesNotMatch(buy, /data-type="discharge"/);
  assert.doesNotMatch(sell, /data-type="charge"/);

  const importBars = priceBars(buy), exportBars = priceBars(sell);
  assert.equal(importBars.length, 3, 'null import is a gap');
  assert.equal(exportBars.length, 4);
  assert.deepEqual(importBars.map(bar => bar.x), exportBars.slice(0, 3).map(bar => bar.x));
  assert.ok(importBars[1].height > importBars[0].height, 'import uses its own price during discharge');
  assert.equal(importBars[2].height, 2, 'zero import stays visible');
  assert.equal(exportBars[3].height, 2, 'zero export stays visible');
  assert.equal(importBars[0].fill, 'var(--vcc-success, #4caf50)');
  assert.equal(importBars[1].fill, 'var(--vcc-disabled, #bdbdbd)');
  assert.equal(exportBars[0].fill, 'var(--vcc-disabled, #bdbdbd)');
  assert.equal(exportBars[1].fill, '#ff6600');
  assert.match(buy, /class="plan-pv-column"/);
  assert.doesNotMatch(sell, /class="plan-pv-column"/);

  const tooltip = chart => chart.match(/<foreignObject.*?<\/foreignObject>/s)?.[0];
  card._onBarClick({}, 'today-charge', 0);
  const importDetails = tooltip(priceCharts(flush())[0]);
  assert.equal((importDetails.match(/ct\/kWh/g) || []).length, 1);
  assert.match(importDetails, /<th>From<\/th><th>Import<\/th><th>Export<\/th><th>Plan<\/th>/);
  for (const cells of [
    ['01:00', '4.00', '-5.00', 'Charging'],
    ['01:15', '10.00', '7.00', 'Discharging'],
    ['01:30', '0.00', '12.00', 'PV Charging'],
    ['01:45', '—', '0.00', 'Idle'],
  ]) assert.ok(importDetails.includes(`<tr>${cells.map(cell => `<td>${cell}</td>`).join('')}</tr>`));
  assert.doesNotMatch(buy, /<title>/);
  assert.match(buy, /Import 4\.00 ct\/kWh · Export -5\.00 ct\/kWh · Charging/);
  card._onBarClick({}, 'today-discharge', 0);
  assert.equal(tooltip(priceCharts(flush())[1]), importDetails);

  const changes = [];
  card._thresholdDrag = { scale: { ...card._priceChartData().plots[0].scale, direction: 'charge' } };
  card._finishThresholdDrag = commit => { changes.push(commit); card._thresholdDrag = null; };
  push({ ...states, 'text.garage_sell_price': { state: '200' } });
  assert.deepEqual(changes, [], 'export scale changes preserve an import drag');
  push({ ...card.hass.states, 'text.garage_buy_price': { state: '200' } });
  assert.deepEqual(changes, [false], 'import scale changes cancel an import drag');
});

test('Each directional scale includes its off-scale cutoff, and drags cancel when that scale changes', () => {
  const { card, push, flush } = setup();
  const plan = ['2026-10-15', '2026-10-16'].map(date => ({ date, hour: 1, price: 100,
    import_price: 4, export_price: 100, action: 'discharge',
  }));
  const states = {
    ...card.hass.states,
    'text.garage_sell_price': { state: '100' },
    'switch.garage_relative_auto_mode': { state: 'on' },
    'number.garage_charge_price_threshold': { state: '10' },
    'number.garage_discharge_price_threshold': { state: '10' },
  };
  const publish = overrides => push({ ...states, 'sensor.garage_charge_plan': { state: 'ready', attributes: {
    plan, price_formula_configured: true, price_reference_min: 100, price_reference_max: 4, ...overrides,
  } } });
  publish();
  const charts = priceCharts(flush());
  assert.equal(charts.length, 4);
  for (const [index, chart] of charts.entries()) {
    const expected = index % 2 === 0 ? ['charge', '-6'] : ['discharge', '110'];
    assert.deepEqual(chart.match(/class="threshold-line-group" data-type="([^"]+)"[\s\S]*?class="plan-threshold-label"[^>]*>([^<]+)/)?.slice(1), expected);
  }
  assert.deepEqual(axisValues(charts[0]), axisValues(charts[2]));
  assert.deepEqual(axisValues(charts[1]), axisValues(charts[3]));
  assert.equal(Math.min(...axisValues(charts[0])), -7);
  assert.equal(Math.max(...axisValues(charts[1])), 111);

  const changes = [];
  card._thresholdDrag = { scale: { ...card._priceChartData().plots[1].scale, direction: 'discharge' } };
  card._finishThresholdDrag = commit => { changes.push(commit); card._thresholdDrag = null; };
  push({ ...card.hass.states, 'sensor.garage_current_price': { state: '4' } });
  assert.deepEqual(changes, [], 'fresh HA data with matching cutoff and prices keeps the drag');
  push({ ...card.hass.states, 'number.garage_discharge_price_threshold': { state: '20' } });
  assert.deepEqual(changes, [false], 'the external delta expands the scale and cancels the active drag');

  publish({ price_reference_min: null, price_reference_max: null });
  const [, sellWithoutReference] = priceCharts(flush());
  assert.equal(Math.max(...axisValues(sellWithoutReference)), 101);
  assert.doesNotMatch(flush(), /class="threshold-line-group"/);
  publish({ price_formula_configured: false });
  assert.equal(priceCharts(flush()).length, 2);
  assert.doesNotMatch(flush(), /class="threshold-line-group"/);
});

test('Split Price pickers use both labeled prices for the same canonical interval', () => {
  const { card, push, flush } = setup();
  const entity = 'sensor.garage_charge_plan';
  const plan = directionalPlan();
  plan[0] = { ...plan[0], action: 'idle', price: 5, import_price: 5, export_price: 100 };
  const publish = (price_formula_configured, periods = plan) => push({ ...card.hass.states,
    [entity]: { state: 'ready', attributes: { price_formula_configured, plan: periods } },
  });
  publish(true);
  flush();
  for (const chartId of ['today-charge', 'today-discharge']) {
    card._openPicker(chartId, 0);
    const picker = card._renderPlanPicker();
    assert.match(picker, /Import 5\.00 ct\/kWh · Export 100\.00 ct\/kWh · Idle/);
    assert.match(picker, /Import unavailable · Export 0\.00 ct\/kWh · Idle/);
    assert.equal(card._pickerBar.selected.size, 4);
    assert.equal(card._currentPickerPeriod(card._pickerBar.rows[0]).price, 5);
  }
  publish(true, plan.slice(1));
  assert.equal(card._currentPickerPeriod(card._pickerBar.rows[0]), null, 'a removed canonical interval cannot be selected');
  assert.doesNotMatch(card._renderPlanPicker(), /Import 5\.00 ct\/kWh · Export 100\.00 ct\/kWh/);

  card._closePicker();
  publish(false);
  flush();
  card._openPicker('today', 0);
  assert.match(card._renderPlanPicker(), /<span>5\.00 ct\/kWh · Idle<\/span>/);
  assert.doesNotMatch(card._renderPlanPicker(), /Import|Export/);
});

test('Price respects the explicit formula flag, zero accounting rates and missing sides or days', () => {
  const { card, push, flush } = setup();
  const entity = 'sensor.garage_charge_plan';
  const states = { ...card.hass.states, 'text.garage_buy_price': { state: '0' }, 'text.garage_sell_price': { state: '0' } };
  const today = directionalPlan().map(({ export_price, ...entry }) => entry);
  const missing = { date: '2026-10-16', hour: 1, action: 'idle' };
  const publish = (attrs, plan = [...today, missing]) => push({ ...states, [entity]: { state: 'ready', attributes: { ...attrs, plan } } });

  for (const attrs of [{}, { price_formula_configured: false }, { price_formula_configured: 'true' }]) {
    publish(attrs, directionalPlan());
    const rendered = flush();
    assert.equal(priceCharts(rendered).length, 1);
    assert.doesNotMatch(rendered, /Import · Charging|Export · Discharging/);
    assert.match(rendered, />Buy \/ Sell 0<\/text>/);
    assert.match(rendered, /fill="#ff6600"/);
  }

  const attrs = { price_formula_configured: true };
  publish(attrs);
  const rendered = flush();
  const [buy, sell] = priceCharts(rendered);
  assert.equal(axisValues(buy).length, 5);
  assert.match(buy, />Buy accounting 0<\/text>/);
  assert.match(sell, />Sell accounting 0<\/text>/);
  assert.equal(priceBars(sell).length, 0);
  assert.match(rendered, /Export prices unavailable/);
  assert.match(rendered, /Tomorrow — prices not yet available/);
  assert.match(sell, /Import 0\.00 ct\/kWh · Export unavailable · PV Charging/);
  publish(attrs, [missing, { ...missing, date: today[0].date, price: 45 }]);
  assert.match(flush(), /No EPEX price data available/);
  assert.equal(priceCharts(flush()).length, 0);
});
