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
  card._pendingThresholds.charge = 8;
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
  assert.equal(card._pendingThresholds.charge, 8, 'threshold pending semantics stay separate');
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
