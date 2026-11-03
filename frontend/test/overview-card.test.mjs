import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import { normalizeView } from '../src/view.mjs';
import * as forecast from '../src/solar-forecast.mjs';

// Capture real Lit bindings so tests can invoke the rendered control handlers.
const source = readFileSync(new URL('../src/victron-charge-controller-card.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '')
  .replace(/registerCard\(\);\s*$/, 'globalThis.Card = VictronChargeControllerCard; globalThis.Editor = VictronChargeControllerCardEditor;');

function setup({ mode = 'auto', charge = 'on', discharge = 'off', prefix = 'garage_victron' } = {}) {
  const templates = [], calls = [];
  const template = (strings, ...values) => {
    const rendered = strings.reduce((text, string, i) => text + string + (values[i] ?? ''), '');
    templates.push({ strings, values, rendered });
    return rendered;
  };
  const context = vm.createContext({
    ...forecast, normalizeView, html: template, svg: template, css: template, nothing: '',
    LitElement: class { requestUpdate() {} dispatchEvent(event) { this.lastEvent = event; } },
    CustomEvent: class { constructor(type, options) { this.type = type; Object.assign(this, options); } },
    document: { addEventListener() {}, removeEventListener() {} },
    window: { removeEventListener() {} }, setTimeout, clearTimeout,
  });
  vm.runInContext(source, context);
  const card = new context.Card();
  card.setConfig({ view: ' Overview ', entity_prefix: prefix });
  const states = {};
  for (const [domain, key, state] of [
    ['select', 'control_mode', mode], ['switch', 'charge_allowed', charge],
    ['switch', 'discharge_allowed', discharge], ['sensor', 'current_price', '0.1'],
  ]) if (state !== null) states[`${domain}.${prefix}_${key}`] = { state, attributes: {} };
  states[`sensor.${prefix}_target_setpoint`] = { state: '-450', attributes: { calculation: {
    setting_w: 50, pv_charge_w: 1000, surplus_w: -2000, grid_consumer_w: 500, limits_w: 0,
  } } };
  states[`switch.${prefix}_grid_consumer`] = { state: 'on', attributes: { source_entity: 'sensor.ev_power' } };
  card.hass = { states, callService: (...args) => { calls.push(args); return Promise.resolve(); } };
  return { card, editor: new context.Editor(), templates, calls, states, prefix };
}

function binding(node, name) {
  const index = node.strings.findIndex(string => string.endsWith(`${name}=`));
  assert.notEqual(index, -1, `${name} binding exists`);
  return node.values[index];
}
const modes = templates => templates.filter(node => node.strings.join('').includes('class="mode-btn '));
const switches = templates => templates.filter(node => node.strings.join('').includes('class="toggle-pair-item"'));

for (const state of ['on', 'off', 'unknown', 'unavailable', null]) {
  test(`Settings Disable Discharge binds ${state} state and the configured prefix`, () => {
    const { card, templates, calls, states, prefix } = setup();
    const entityId = `switch.${prefix}_disable_discharge`;
    if (state !== null) states[entityId] = { state, attributes: {} };
    states[`number.${prefix}_charge_power`] = { state: '3000', attributes: {} };
    card.setConfig({ ...card.config, view: 'settings' });
    const rendered = card.render();
    const toggle = switches(templates).find(node => binding(node, 'aria-label') === 'Disable Discharge');
    assert.ok(toggle);
    assert.equal(binding(toggle, '.checked'), state === 'on');
    assert.equal(binding(toggle, '.disabled'), !['on', 'off'].includes(state));
    const pair = templates.find(node => node.strings.join('').includes('class="control-row toggle-pair"')
      && node.rendered.includes('aria-label=Disable Discharge'));
    assert.equal((pair.rendered.match(/class="toggle-pair-item"/g) || []).length, 1);
    assert.ok(rendered.indexOf('aria-label=Discharge Allowed') < rendered.indexOf('aria-label=Disable Discharge'));
    assert.ok(rendered.indexOf('aria-label=Disable Discharge') < rendered.indexOf('Help for Charge Power'));
    assert.equal(calls.length, 0);
    binding(toggle, '@change')();
    assert.deepEqual(JSON.parse(JSON.stringify(calls)), ['on', 'off'].includes(state) ? [[
      'switch', state === 'on' ? 'turn_off' : 'turn_on', { entity_id: entityId },
    ]] : []);
  });
}

test('Disable Discharge remains turnable off during an external entity outage and rechecks switch availability', () => {
  const { card, templates, calls, states, prefix } = setup();
  const entityId = `switch.${prefix}_disable_discharge`;
  states[entityId] = { state: 'on', attributes: {} };
  states['number.max_discharge'] = { state: 'unavailable', attributes: {} };
  card._renderControlsView();
  const toggle = switches(templates).find(node => binding(node, 'aria-label') === 'Disable Discharge');
  assert.equal(binding(toggle, '.disabled'), false);
  binding(toggle, '@change')();
  assert.equal(calls[0][1], 'turn_off');
  states[entityId].state = 'unavailable';
  binding(toggle, '@change')();
  assert.equal(calls.length, 1);
});

test('Disable Discharge opens its existing accessible help dialog with behavior and cleanup limits', () => {
  const { card, templates } = setup();
  card._renderControlsView();
  const label = templates.find(node => node.rendered.includes('aria-label=Help for Disable Discharge'));
  assert.match(label.rendered, /aria-haspopup="dialog"/);
  card._openHelp = topic => { card._helpOpen = true; card._helpTopic = topic; };
  binding(label, '@click')({ currentTarget: {} });
  assert.equal(card._helpTopic.key, 'disable_discharge');
  const rendered = card._renderHelpDialog('settings', 'Settings');
  assert.match(rendered, /role="dialog" aria-modal="true" aria-label=Disable Discharge/);
  for (const text of ['0 W', '5 seconds', 'regular Charge slots and Force Charge', 'Max SOC',
    'zero Charge Power', 'Charge Allowed off', 'PV Charge is excluded', '−1 W', 'watchdog stop',
    'previous numerical limit is not restored', 'defaults off', 'logged and retried',
    'Pending release survives restart and reconfiguration', 'orderly shutdown', 'crash or outage']) {
    assert.ok(rendered.includes(text), text);
  }
  assert.doesNotMatch(card._renderOverviewView(), /Disable Discharge/);
  assert.doesNotMatch(card._renderPlanView(), /Disable Discharge/);
});

test('Overview routes from normalized configuration, shows compact controls and server calculation without writes', () => {
  const { card, calls } = setup();
  const rendered = card.render();
  for (const label of ['Overview', 'Mode', 'Settings', 'Charge Allowed', 'Discharge Allowed', 'Grid Consumer', 'Setting', 'PV charge', 'Surplus', 'Grid consumer', 'Grid setpoint']) {
    assert.ok(rendered.includes(label), label);
  }
  assert.match(rendered, /\+50 W/);
  assert.match(rendered, /−2,000 W/);
  assert.match(rendered, /<strong>−450 W<\/strong>/);
  assert.match(rendered, /10\.00 ct\/kWh/);
  assert.doesNotMatch(rendered, /Charge \/ Discharge|Battery Limits|Blocked Hours|Replan Hours|slider-row/);
  assert.equal(card.getCardSize(), 6);
  assert.equal(calls.length, 0);
  card.setConfig({});
  assert.equal(card.config.view, 'settings');
  assert.equal(card.getCardSize(), 12);
});

for (const mode of ['off', 'auto', 'manual', 'force_charge', 'force_discharge']) {
  test(`Overview selects ${mode} through the configured entity prefix`, () => {
    const { card, templates, calls, prefix } = setup({ mode });
    card.render();
    const buttons = modes(templates);
    assert.equal(buttons.length, 5);
    assert.equal(buttons.filter(node => binding(node, 'aria-pressed')).length, 1);
    const button = buttons.find(node => binding(node, 'data-mode') === mode);
    assert.equal(binding(button, 'aria-pressed'), true);
    assert.equal(binding(button, '?disabled'), false);
    binding(button, '@click')();
    assert.deepEqual(JSON.parse(JSON.stringify(calls)), [['select', 'select_option', {
      entity_id: `select.${prefix}_control_mode`, option: mode,
    }]]);
  });
}

for (const state of ['on', 'off']) test(`Overview permission switches in ${state} state use their correct services`, () => {
  const { card, templates, calls, prefix } = setup({ charge: state, discharge: state });
  card.render();
  const toggles = switches(templates);
  assert.equal(toggles.length, 2);
  toggles.forEach(node => {
    assert.equal(binding(node, '.checked'), state === 'on');
    assert.equal(binding(node, '.disabled'), false);
    binding(node, '@change')();
  });
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), ['charge_allowed', 'discharge_allowed'].map(key => [
    'switch', state === 'on' ? 'turn_off' : 'turn_on', { entity_id: `switch.${prefix}_${key}` },
  ]));
});

for (const state of [null, 'unknown', 'unavailable']) {
  test(`Overview handles ${state} permissions independently and blocks their handlers`, () => {
    const { card, templates, calls } = setup({ charge: state });
    card.render();
    const toggles = switches(templates);
    assert.equal(binding(toggles[0], '.disabled'), true);
    assert.equal(binding(toggles[1], '.disabled'), false);
    binding(toggles[0], '@change')();
    assert.equal(calls.length, 0);
  });

  test(`Overview blocks mode changes when current mode is ${state}`, () => {
    const { card, templates, calls } = setup({ mode: state });
    const rendered = card.render();
    if (state === null) assert.match(rendered, /entities not found/);
    else {
      for (const button of modes(templates)) {
        assert.equal(binding(button, '?disabled'), true);
        assert.equal(binding(button, 'aria-pressed'), false);
        binding(button, '@click')();
      }
    }
    card._selectMode('force_charge');
    assert.equal(calls.length, 0);
  });
}

test('controls recheck availability if entities become unavailable after rendering', () => {
  const { card, templates, states, calls, prefix } = setup();
  card.render();
  states[`select.${prefix}_control_mode`].state = 'unavailable';
  states[`switch.${prefix}_charge_allowed`].state = 'unavailable';
  binding(modes(templates)[1], '@click')();
  binding(switches(templates)[0], '@change')();
  assert.equal(calls.length, 0);
});

test('Overview displays a capped target and preserves zero and unavailable calculation states', () => {
  const { card, states, prefix } = setup();
  const sensor = states[`sensor.${prefix}_target_setpoint`];
  sensor.state = '-400';
  sensor.attributes.calculation.limits_w = 50;
  assert.match(card.render(), /<strong>−400 W \(−450 W\)<\/strong>/);
  const consumerId = `switch.${prefix}_grid_consumer`;
  for (const consumer of [
    undefined,
    { state: 'on', attributes: {} },
    { state: 'on', attributes: { source_entity: null } },
    ...['off', 'unknown', 'unavailable'].map(state => ({ state, attributes: { source_entity: 'sensor.ev_power' } })),
  ]) {
    states[consumerId] = consumer;
    const rendered = card.render();
    assert.doesNotMatch(rendered, /<dt>Grid consumer<\/dt>/);
    assert.match(rendered, /<strong>−400 W \(−450 W\)<\/strong>/);
  }
  states[consumerId] = { state: 'on', attributes: { source_entity: 'sensor.ev_power' } };
  assert.match(card.render(), /<dt>Grid consumer<\/dt>/);
  sensor.state = '0';
  Object.keys(sensor.attributes.calculation).forEach(key => { sensor.attributes.calculation[key] = 0; });
  assert.match(card.render(), /<strong>0 W<\/strong>/);
  assert.match(card.render(), /<dt>Grid consumer<\/dt>/);
  sensor.state = 'unavailable';
  assert.match(card.render(), /Calculation unavailable/);
  assert.match(card.render(), /<strong>—<\/strong>/);
  delete states[`sensor.${prefix}_target_setpoint`];
  assert.match(card.render(), /Calculation unavailable/);
});

test('Overview help works and editor selection emits the existing config-changed event', () => {
  const { card, editor, templates } = setup();
  card._helpOpen = true;
  assert.match(card.render(), /Help – Overview/);
  assert.match(card.render(), /Grid setpoint calculation/);
  editor.setConfig({ type: 'custom:victron-charge-controller-card', view: 'overview', entity_prefix: 'garage' });
  assert.match(editor.render(), /value="overview" \?selected=true/);
  const select = templates.find(node => node.strings.join('').includes('<select id="view"'));
  binding(select, '@change')({ target: { value: 'overview' } });
  assert.equal(editor.lastEvent.type, 'config-changed');
  assert.equal(editor.lastEvent.detail.config.view, 'overview');
  assert.equal(editor.lastEvent.detail.config.entity_prefix, 'garage');
});

test('Settings retains mode, permissions and tuning without Overview status; other views keep their routing', () => {
  const { card, calls } = setup();
  card.setConfig({ ...card.config, view: 'settings' });
  const settings = card.render();
  for (const label of ['Settings', 'Mode', 'Charge Allowed', 'Discharge Allowed', 'Battery Limits', 'Blocked Hours']) {
    assert.ok(settings.includes(label), label);
  }
  assert.doesNotMatch(settings, /setpoint-calculation|setpoint-result|status-row|10\.00 ct\/kWh/);
  for (const view of ['plan', 'history']) {
    card.setConfig({ ...card.config, view });
    card[view === 'plan' ? '_renderPlanView' : '_renderHistoryView'] = () => `${view}-content`;
    assert.ok(card.render().includes(`${view}-content`));
  }
  assert.equal(calls.length, 0);
});

for (const state of ['on', 'off', 'unknown', 'unavailable', null]) {
  test(`Battery Power Control binds ${state} and targets the configured prefix`, () => {
    const { card, templates, calls, states, prefix } = setup();
    const entityId = `switch.${prefix}_battery_power_control`;
    if (state !== null) states[entityId] = { state, attributes: { source_entity: 'sensor.battery', feedback_status: 'active' } };
    card._renderControlsView();
    const toggle = templates.find(node => node.strings.join('').includes('class="control-row toggle-row"')
      && node.rendered.includes('aria-label=Battery Power Control'));
    assert.equal(binding(toggle, '.checked'), state === 'on');
    assert.equal(binding(toggle, '.disabled'), !['on', 'off'].includes(state));
    binding(toggle, '@change')();
    assert.deepEqual(JSON.parse(JSON.stringify(calls)), ['on', 'off'].includes(state) ? [[
      'switch', state === 'on' ? 'turn_off' : 'turn_on', { entity_id: entityId },
    ]] : []);
  });
}

test('Battery Power Control explains missing configuration and permits off during sensor outage', () => {
  const { card, templates, calls, states, prefix } = setup();
  const entityId = `switch.${prefix}_battery_power_control`;
  states[entityId] = { state: 'off', attributes: { source_entity: null } };
  assert.match(card._renderBatteryPowerControl(), /Configure a Battery power sensor/);
  const disabled = templates.find(node => node.strings.join('').includes('class="control-row toggle-row"'));
  assert.equal(binding(disabled, '.disabled'), true);
  binding(disabled, '@change')();
  assert.equal(calls.length, 0);
  states[entityId] = { state: 'on', attributes: { source_entity: 'sensor.battery', power_w: null, feedback_status: 'fallback' } };
  states['sensor.battery'] = { state: 'unavailable', attributes: {} };
  templates.length = 0;
  assert.match(card._renderBatteryPowerControl(), /role="status".*invalid, unavailable or stale/s);
  const enabled = templates.find(node => node.strings.join('').includes('class="control-row toggle-row"'));
  assert.equal(binding(enabled, '.disabled'), false);
  binding(enabled, '@change')();
  assert.equal(calls[0][1], 'turn_off');
  states[entityId].state = 'unavailable';
  binding(enabled, '@change')();
  assert.equal(calls.length, 1);
});

for (const [status, message] of [
  ['waiting', 'Waiting for a baseline or settled battery reading before the next feedback adjustment.'],
  ['fallback', 'grid-only control is active with the existing offsets'],
  ['inactive', 'Battery feedback is inactive for the current action'],
  ['active', 'Battery feedback is active; Charge / Discharge Power targets battery watts.'],
]) test(`Battery Power Control displays accessible ${status} status`, () => {
  const { card, states, prefix } = setup();
  states[`switch.${prefix}_battery_power_control`] = { state: 'on', attributes: {
    source_entity: 'sensor.battery', feedback_status: status,
  } };
  states[`number.${prefix}_charge_power`] = { state: '3000', attributes: {} };
  const rendered = card._renderControlsView();
  assert.ok(rendered.includes(message));
  assert.match(rendered, /role="status"/);
  assert.ok(rendered.indexOf('aria-label=Battery Power Control') < rendered.indexOf('Help for Charge Power'));
  states[`switch.${prefix}_battery_power_control`].state = 'off';
  assert.ok(!card._renderBatteryPowerControl().includes(message));
});

for (const sign of [1, -1]) test(`Overview includes signed battery feedback and clamps (${sign})`, () => {
  const { card, states, prefix } = setup();
  const sensor = states[`sensor.${prefix}_target_setpoint`];
  sensor.attributes.calculation = { setting_w: sign * 3000, battery_feedback_w: sign * 1000,
    pv_charge_w: 0, surplus_w: 0, grid_consumer_w: 0, limits_w: sign * -500 };
  sensor.state = String(sign * 3500);
  const rendered = card.render();
  assert.match(rendered, /<dt>Battery feedback<\/dt>/);
  assert.ok(rendered.includes(`${sign > 0 ? '+' : '−'}1,000 W`));
  assert.ok(rendered.includes(`<strong>${sign > 0 ? '' : '−'}3,500 W (${sign > 0 ? '' : '−'}4,000 W)</strong>`));
});

test('Overview hides zero or absent battery feedback and preserves consumer terms', () => {
  const { card, states, prefix } = setup();
  const calculation = states[`sensor.${prefix}_target_setpoint`].attributes.calculation;
  for (const present of [false, true]) {
    if (present) calculation.battery_feedback_w = 0;
    const rendered = card.render();
    assert.doesNotMatch(rendered, /Calculation unavailable|<dt>Battery feedback<\/dt>/);
    assert.match(rendered, /<dt>Grid consumer<\/dt>/);
    assert.match(rendered, /<strong>−450 W<\/strong>/);
  }
});

for (const value of [NaN, Infinity, -Infinity, null, undefined, '1000']) {
  test(`Overview rejects explicitly invalid battery feedback ${String(value)}`, () => {
    const { card, states, prefix } = setup();
    states[`sensor.${prefix}_target_setpoint`].attributes.calculation.battery_feedback_w = value;
    assert.match(card.render(), /Calculation unavailable/);
  });
}

test('Battery Power Control help explains configuration, sampling, coexistence and limits', () => {
  const { card, templates } = setup();
  card._renderBatteryPowerControl();
  const label = templates.find(node => node.rendered.includes('aria-label=Help for Battery Power Control'));
  card._openHelp = topic => { card._helpOpen = true; card._helpTopic = topic; };
  binding(label, '@click')({ currentTarget: {} });
  const rendered = card._renderHelpDialog('settings', 'Settings');
  for (const text of ['W or kW', 'positive when charging', 'negative when discharging', 'defaults off',
    'restored after restart', 'PV Charge', 'solar-only discharge', 'each new battery reading once', 'five seconds',
    '120 seconds', 'changing the grid target before adjusting again', 'Grid Consumer offsets', 'SOC protection', 'not guaranteed']) {
    assert.ok(rendered.includes(text), text);
  }
});
