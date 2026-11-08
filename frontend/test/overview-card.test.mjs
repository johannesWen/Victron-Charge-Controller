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
    assert.equal(binding(toggle, 'title'), ['on', 'off'].includes(state) ? ''
      : 'Configure a Maximum discharge power entity in the integration options to enable Disable Discharge.');
    assert.equal(binding(toggle, 'tabindex'), ['on', 'off'].includes(state) ? '' : '0');
    const pair = templates.find(node => node.strings.join('').includes('class="control-row toggle-pair"')
      && node.rendered.includes('aria-label=Disable Discharge'));
    assert.equal((pair.rendered.match(/class="toggle-pair-item"/g) || []).length, 2);
    assert.ok(pair.rendered.indexOf('aria-label=Battery Power Control') < pair.rendered.indexOf('aria-label=Disable Discharge'));
    assert.ok(rendered.indexOf('aria-label=Discharge Allowed') < rendered.indexOf('aria-label=Disable Discharge'));
    assert.ok(rendered.indexOf('aria-label=Disable Discharge') < rendered.indexOf('Help for Grid Consumer'));
    assert.ok(rendered.indexOf('Help for Grid Consumer') < rendered.indexOf('Help for Charge Power'));
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
  for (const text of ['0 W', '5 seconds', 'regular Charge periods and Force Charge', 'Max SOC',
    'Charge Power is 0 W', 'Charge Allowed is off', 'PV Charge is not included', '−1 W', 'watchdog safety check',
    'does not put back the previous limit', 'starts off', 'logged and retried',
    'remembered after a restart or configuration change', 'normal shutdown', 'crash or outage', 'Example:']) {
    assert.ok(rendered.includes(text), text);
  }
  assert.doesNotMatch(card._renderOverviewView(), /Disable Discharge/);
  assert.doesNotMatch(card._renderPlanView(), /Disable Discharge/);
});

test('Overview routes from normalized configuration, shows compact controls and server calculation without writes', () => {
  const { card, calls } = setup();
  const rendered = card.render();
  for (const label of ['Overview', 'Mode', 'Settings', 'Charge Allowed', 'Discharge Allowed', 'Grid Consumer', 'Battery Power Control', 'Setting', 'PV charge', 'Surplus', 'Grid consumer', 'Grid setpoint']) {
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
  const toggles = switches(templates).filter(node => ['Charge Allowed', 'Discharge Allowed'].includes(binding(node, 'aria-label')));
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

for (const view of ['settings', 'overview']) for (const state of ['on', 'off', 'unknown', 'unavailable', null]) {
  test(`${view} Battery Power Control binds ${state} and targets the configured prefix`, () => {
    const { card, templates, calls, states, prefix } = setup();
    const entityId = `switch.${prefix}_battery_power_control`;
    if (state !== null) states[entityId] = { state, attributes: { source_entity: 'sensor.battery', feedback_status: 'active' } };
    card.setConfig({ ...card.config, view });
    card.render();
    const toggle = switches(templates).find(node => binding(node, 'aria-label') === 'Battery Power Control');
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
  const disabled = switches(templates).find(node => binding(node, 'aria-label') === 'Battery Power Control');
  assert.equal(binding(disabled, '.disabled'), true);
  binding(disabled, '@change')();
  assert.equal(calls.length, 0);
  states[entityId] = { state: 'on', attributes: { source_entity: 'sensor.battery', power_w: null, feedback_status: 'fallback' } };
  states['sensor.battery'] = { state: 'unavailable', attributes: {} };
  templates.length = 0;
  assert.match(card._renderBatteryPowerControl(), /title=Battery power is invalid, unavailable or stale/);
  const enabled = switches(templates).find(node => binding(node, 'aria-label') === 'Battery Power Control');
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
]) test(`Battery Power Control keeps ${status} in its tooltip without hint text`, () => {
  const { card, templates, states, prefix } = setup();
  states[`switch.${prefix}_battery_power_control`] = { state: 'on', attributes: {
    source_entity: 'sensor.battery', feedback_status: status,
  } };
  states[`number.${prefix}_charge_power`] = { state: '3000', attributes: {} };
  const rendered = card._renderControlsView();
  assert.ok(rendered.includes(message));
  const toggle = switches(templates).find(node => binding(node, 'aria-label') === 'Battery Power Control');
  assert.ok(binding(toggle, 'title').includes(message));
  assert.doesNotMatch(card._renderBatteryPowerControl(), /forecast-status|role="status"/);
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
  for (const text of ['W or kW', 'positive when charging', 'negative when discharging', 'starts off',
    'keeps your choice after a restart', 'PV Charge', 'solar-only discharge', 'each new reading once', '5 seconds',
    '120 seconds', 'changing the grid target before adjusting again', 'solar surplus and Grid Consumer adjustments',
    'Battery level limits', 'battery may not reach the requested power', 'new target 4000 W']) {
    assert.ok(rendered.includes(text), text);
  }
});

function relativeSetup(relative = 'on', mode = 'auto') {
  const result = setup({ mode });
  const { card, states, prefix } = result;
  card.setConfig({ ...card.config, view: 'settings' });
  if (relative !== null) states[`switch.${prefix}_relative_auto_mode`] = { state: relative, attributes: {} };
  for (const [key, value] of Object.entries({
    cheapest_hours_auto_charge: '0', expensive_hours_auto_discharge: '1.25',
    charge_price_threshold: '4', discharge_price_threshold: '6',
  })) states[`number.${prefix}_${key}`] = { state: value, attributes: { min: -10, max: 30, step: .25 } };
  states[`sensor.${prefix}_charge_plan`] = { state: 'ready', attributes: {
    price_reference_min: -8.13, price_reference_max: 24.13,
    plan: [
      { date: '2035-01-01', hour: 12, price: -20, action: 'idle' },
      { date: '2035-01-02', hour: 12, price: 22, action: 'idle' },
    ],
  } };
  return result;
}
const ranges = templates => templates.filter(node => node.strings.join('').includes('<input type="range"'));
const thresholdLines = templates => templates.filter(node => node.strings.join('').includes('class="threshold-line-group"'));
const plain = value => JSON.parse(JSON.stringify(value));

for (const mode of ['off', 'auto', 'manual', 'force_charge', 'force_discharge']) {
  test(`Relative Auto Mode binds the configured prefix and remains available in ${mode}`, () => {
    const { card, templates, calls, prefix } = relativeSetup('off', mode);
    const rendered = card.render();
    const toggle = templates.find(node => node.strings.join('').includes('class="control-row toggle-row relative-mode-toggle"'));
    assert.equal(binding(toggle, '.checked'), false);
    assert.equal(binding(toggle, '.disabled'), false);
    assert.match(toggle.rendered, /Absolute<\/button>[\s\S]*<ha-switch[\s\S]*>Relative<\/button>/);
    const row = templates.find(node => node.strings.join('').includes('class="auto-mode-toggles"'));
    assert.doesNotMatch(row.rendered, /Grid Consumer/);
    assert.ok(rendered.indexOf('Auto Mode') < rendered.indexOf('aria-label="Relative Auto Mode"'));
    binding(toggle, '@change')();
    assert.deepEqual(plain(calls), [['switch', 'turn_on', { entity_id: `switch.${prefix}_relative_auto_mode` }]]);
  });
}

for (const state of [null, 'unknown', 'unavailable', 'off', 'on']) {
  test(`Relative Auto Mode ${state} safely controls labels and duration availability`, () => {
    const { card, states, templates, calls, prefix } = relativeSetup(state);
    const rendered = card.render();
    const toggle = templates.find(node => node.strings.join('').includes('class="control-row toggle-row relative-mode-toggle"'));
    assert.equal(binding(toggle, '.checked'), state === 'on');
    assert.equal(binding(toggle, '.disabled'), !['on', 'off'].includes(state));
    const controls = ranges(templates);
    for (const [label, value] of [['Charge Duration', '0'], ['Discharge Duration', '1.25']]) {
      const control = controls.find(node => binding(node, 'aria-label') === label);
      assert.equal(binding(control, '.disabled'), state === 'on');
      assert.equal(binding(control, '.value'), value);
    }
    for (const type of ['Charge', 'Discharge']) {
      assert.ok(controls.some(node => binding(node, 'aria-label') === `${type} Price ${state === 'on' ? 'Delta' : 'Threshold'}`));
    }
    assert.doesNotMatch(rendered, /Duration budgets are ignored.*Saved duration values are retained/);
    if (!['on', 'off'].includes(state)) {
      assert.match(rendered, /switch is unavailable; absolute price settings are shown/);
      assert.equal(binding(toggle, 'role'), 'group');
      assert.match(binding(toggle, 'aria-label'), /Relative Auto Mode switch is unavailable/);
      binding(toggle, '@change')();
      assert.equal(calls.length, 0);
    } else {
      states[`switch.${prefix}_relative_auto_mode`].state = 'unavailable';
      binding(toggle, '@change')();
      assert.equal(calls.length, 0, 'handler rechecks current switch availability');
    }
  });
}

test('duration handlers reject disabled changes and resume using retained values after relative mode turns off', () => {
  const { card, states, templates, calls, prefix } = relativeSetup();
  card.render();
  const control = ranges(templates).find(node => binding(node, 'aria-label') === 'Discharge Duration');
  const input = { disabled: true, value: '10', dataset: { lockedValue: '1.25' }, classList: { remove() {} },
    parentElement: { querySelector: () => ({ style: {} }) } };
  card._sliderUnlocked.add(input);
  binding(control, '@pointerdown')({ target: input });
  assert.equal(card._sliderHoldTimers.has(input), false);
  binding(control, '@input')({ target: input });
  assert.equal(input.value, '1.25');
  input.value = '10';
  binding(control, '@change')({ target: input });
  assert.equal(input.value, '1.25');
  assert.equal(card._sliderUnlocked.has(input), false);
  assert.equal(calls.length, 0);
  input.disabled = false;
  input.value = '10';
  card._sliderUnlocked.add(input);
  binding(control, '@change')({ target: input });
  assert.equal(calls.length, 0, 'mode-change race before disabled binding updates cannot commit');
  states[`switch.${prefix}_relative_auto_mode`].state = 'off';
  templates.length = 0;
  card.render();
  const restored = ranges(templates).find(node => binding(node, 'aria-label') === 'Discharge Duration');
  assert.equal(binding(restored, '.disabled'), false);
  assert.equal(binding(restored, '.value'), '1.25');
  input.value = '2.5';
  card._sliderUnlocked.add(input);
  binding(restored, '@change')({ target: input });
  assert.deepEqual(plain(calls), [['number', 'set_value', { entity_id: `number.${prefix}_expensive_hours_auto_discharge`, value: 2.5 }]]);
});

for (const relative of ['off', 'on']) test(`every Settings help dialog has an example with Relative mode ${relative}`, () => {
  const { card, templates, calls, states, prefix } = relativeSetup(relative);
  states[`switch.${prefix}_grid_feed_in_control`] = { state: 'on', attributes: {} };
  for (const key of ['charge_power', 'discharge_power', 'pv_charging_battery_share',
    'min_soc', 'max_soc', 'soc_hysteresis', 'idle_setpoint', 'min_grid_setpoint', 'max_grid_setpoint',
    'grid_feed_in_price_threshold', 'default_max_grid_feed_in', 'reduced_max_grid_feed_in']) {
    states[`number.${prefix}_${key}`] = { state: '1', attributes: { min: 0, max: 100, step: 1 } };
  }
  card.render();
  const helpButtons = templates.filter(node => /setting-help-label|setting-help-icon/.test(node.strings.join('')));
  const topics = new Set();
  card._openHelp = topic => { card._helpOpen = true; card._helpTopic = topic; };
  for (const button of helpButtons) {
    binding(button, '@click')({ currentTarget: {} });
    const { key } = card._helpTopic;
    topics.add(key);
    const rendered = card._renderHelpDialog('settings', 'Settings');
    assert.match(rendered, /Example:/, key);
    if (key === 'control_mode' || key === 'schedule_actions') {
      assert.equal((rendered.match(/Example:/g) || []).length, key === 'control_mode' ? 5 : 2);
    }
  }
  assert.equal(topics.size, 30, 'all Settings help topics are reachable');
  card._helpTopic = null;
  assert.match(card._renderHelpDialog('settings', 'Settings'), /SOC means battery level/);
  assert.equal(calls.length, 0);
});

for (const relative of ['off', 'on']) test(`Absolute and Relative labels open their own help with Relative mode ${relative}`, () => {
  const { card, templates, calls } = relativeSetup(relative);
  card.render();
  card._openHelp = topic => { card._helpOpen = true; card._helpTopic = topic; };
  for (const name of ['Absolute', 'Relative']) {
    const label = templates.find(node => node.rendered.includes(`aria-label=Help for ${name}`));
    assert.match(label.rendered, /aria-haspopup="dialog"/);
    binding(label, '@click')({ currentTarget: {} });
    assert.equal(card._helpTopic.key, `${name.toLowerCase()}_auto_mode`);
    const rendered = card._renderHelpDialog('settings', 'Settings');
    assert.ok(rendered.includes(`role="dialog" aria-modal="true" aria-label=${name}`));
    if (name === 'Absolute') {
      assert.match(rendered, /up to 2 hours.*10 ct\/kWh or less/);
      assert.match(rendered, /duration of 0 h selects no periods/);
      assert.match(rendered, /discharge wins/);
      assert.doesNotMatch(rendered, /30 − 10 = 20|Duration limits do not apply/);
    } else {
      assert.match(rendered, /30 − 10 = 20/);
      assert.match(rendered, /Duration limits do not apply/);
      assert.match(rendered, /charging wins/);
      assert.doesNotMatch(rendered, /up to 2 hours/);
    }
  }
  assert.equal(calls.length, 0);
});

test('relative help follows the active mode, retains numeric ranges, and explains schedule timing', () => {
  const { card, states, prefix } = relativeSetup();
  card._helpOpen = true;
  card._helpTopic = { key: 'charge_price_threshold', label: 'Charge Price Threshold', unit: ' ct/kWh' };
  let rendered = card._renderHelpDialog('settings', 'Settings');
  for (const text of ['aria-label=Charge Price Delta', 'price difference', 'negative delta', 'exactly at that result are included',
    '30 − 10 = 20', 'before blocked hours and PV Charge', 'Charging wins', 'Charge Duration at 0 h',
    'Minimum', '-10 ct/kWh', '30 ct/kWh', '0.25 ct/kWh']) assert.ok(rendered.includes(text), text);
  card._helpTopic = { key: 'discharge_price_threshold', label: 'Discharge Price Delta' };
  assert.match(card._renderHelpDialog('settings', 'Settings'), /5 \+ 10 = 15/);
  card._helpTopic = { key: 'cheapest_hours_auto_charge', label: 'Charge Duration' };
  assert.match(card._renderHelpDialog('settings', 'Settings'), /not used in Relative mode[\s\S]*even if the saved duration is 0 h[\s\S]*saved duration is kept/);
  card._helpTopic = { key: 'relative_auto_mode', label: 'Relative Auto Mode' };
  rendered = card._renderHelpDialog('settings', 'Settings');
  for (const text of ['switch to the right', 'zero or negative', 'tomorrow or later', 'charging wins',
    'Permission switches', 'battery level limits', 'any mode', 'only rebuilds the schedule in Auto',
    'saved mode and schedule return without rebuilding', 'chart lines without changing the plan']) assert.ok(rendered.includes(text), text);
  for (const key of ['control_mode', 'schedule_actions']) {
    card._helpTopic = { key, label: key };
    assert.match(card._renderHelpDialog('settings', 'Settings'), /Relative mode uses price differences[\s\S]*no duration limit/);
  }
  card._helpTopic = null;
  assert.match(card._renderHelpDialog('plan', 'Plan'), /Lines reflect current selection cutoffs/);
  states[`switch.${prefix}_relative_auto_mode`].state = 'off';
  card._helpTopic = { key: 'charge_price_threshold', label: 'Charge Price Delta', unit: ' ct/kWh' };
  rendered = card._renderHelpDialog('settings', 'Settings');
  assert.match(rendered, /aria-label=Charge Price Threshold/);
  assert.match(rendered, /up to Charge Duration/);
  assert.doesNotMatch(rendered, /price difference/);
});

function chartCutoffs(result) {
  const { card, templates } = result;
  templates.length = 0;
  card._renderAutoPlanContent();
  return thresholdLines(templates).map(node => {
    const label = node.rendered.match(/class="plan-threshold-label"[^>]*>([^<]+)</);
    return [node.strings.join('').includes('data-type="charge"') ? 'charge' : 'discharge', Number(label[1])];
  });
}

test('both days use global backend references, with delta pending values reconciled against number entities', () => {
  const result = relativeSetup(), { card, states, prefix } = result;
  assert.deepEqual(chartCutoffs(result), [['charge', 20.1], ['discharge', -2.1], ['charge', 20.1], ['discharge', -2.1]]);
  // Neither displayed day's extrema (-20 and 22) equals the backend's full selection horizon.
  card._pendingThresholds = { charge: 5.25, discharge: -1.5 };
  assert.deepEqual(chartCutoffs(result), [['charge', 18.9], ['discharge', -9.6], ['charge', 18.9], ['discharge', -9.6]]);
  assert.equal(card._pendingThresholds.charge, 5.25);
  states[`number.${prefix}_charge_price_threshold`].state = '5.25';
  states[`number.${prefix}_discharge_price_threshold`].state = '-1.5';
  chartCutoffs(result);
  assert.deepEqual(plain(card._pendingThresholds), {});
  states[`sensor.${prefix}_charge_plan`].attributes.price_reference_max = 23.13;
  assert.equal(chartCutoffs(result)[0][1], 17.9, 'reference refresh changes the cutoff without a service or replan');
  assert.equal(result.calls.length, 0);
});

for (const missing of [null, undefined, NaN, Infinity, -Infinity, '24.13']) {
  test(`relative chart hides invalid references ${String(missing)} without substituting displayed prices`, () => {
    const result = relativeSetup(), attrs = result.states[`sensor.${result.prefix}_charge_plan`].attributes;
    attrs.price_reference_min = attrs.price_reference_max = missing;
    assert.deepEqual(chartCutoffs(result), []);
    assert.doesNotMatch(result.card._renderAutoPlanContent(), /Charge Cutoff|Discharge Cutoff/);
  });
}

test('zero references are valid and missing switch preserves absolute lines and clears pending units on mode changes', () => {
  const result = relativeSetup(null), { card, states, prefix } = result;
  assert.deepEqual(chartCutoffs(result), [['charge', 4], ['discharge', 6], ['charge', 4], ['discharge', 6]]);
  card._pendingThresholds = { charge: 7 };
  states[`switch.${prefix}_relative_auto_mode`] = { state: 'on', attributes: {} };
  chartCutoffs(result);
  assert.deepEqual(plain(card._pendingThresholds), {});
  states[`sensor.${prefix}_charge_plan`].attributes.price_reference_min = 0;
  states[`sensor.${prefix}_charge_plan`].attributes.price_reference_max = 0;
  states[`number.${prefix}_charge_price_threshold`].state = '-4';
  assert.deepEqual(chartCutoffs(result), [['charge', 4], ['discharge', 6], ['charge', 4], ['discharge', 6]]);
  card._pendingThresholds = { discharge: 9 };
  states[`switch.${prefix}_relative_auto_mode`].state = 'off';
  chartCutoffs(result);
  assert.deepEqual(plain(card._pendingThresholds), {});
});

function startThresholdDrag(result, type, timers) {
  const { card, templates } = result;
  card.classList = { add() {}, remove() {} };
  card._addThresholdDragListeners = () => {};
  card._removeThresholdDragListeners = () => {};
  card._clientToSvgY = value => value;
  card._renderAutoPlanContent();
  const line = thresholdLines(templates).find(node => node.strings.join('').includes(`data-type="${type}"`));
  assert.ok(line, `${type} line rendered`);
  const initialLabel = line.rendered.match(/<text[^>]*y="([^"]+)"[^>]*class="plan-threshold-label"[^>]*>([^<]+)</);
  const marker = { nodeType: 8, nodeValue: '?lit$marker$' };
  const text = { nodeType: 3, nodeValue: initialLabel[2] };
  const position = { y: initialLabel[1] };
  const label = { childNodes: [marker, text], lastChild: text, getAttribute: key => position[key],
    setAttribute: (key, value) => { position[key] = String(value); },
    set textContent(_) { assert.fail('must retain Lit markers'); } };
  const lines = [...line.rendered.matchAll(/<line[^>]*y1="([^"]+)"[^>]*y2="([^"]+)"/g)].map(([, y1, y2]) => ({
    attributes: { y1, y2 }, getAttribute(key) { return this.attributes[key]; },
    setAttribute(key, value) { this.attributes[key] = String(value); },
  }));
  assert.equal(lines.length, 2, 'both visible line and hit area are present');
  const original = { lines: lines.map(line => ({ ...line.attributes })), y: position.y, text: text.nodeValue };
  const assertRestored = () => {
    assert.deepEqual(lines.map(line => line.attributes), original.lines, 'restore both coordinates of both lines');
    assert.equal(position.y, original.y, 'restore label position');
    assert.equal(text.nodeValue, original.text, 'restore label text');
    assert.equal(label.childNodes[0], marker, 'preserve Lit comment marker');
    assert.equal(label.childNodes[1], text, 'preserve Lit text node');
  };
  const group = { classList: { add() {}, remove() {} }, closest: () => ({}), querySelectorAll: () => lines,
    querySelector: () => label, setPointerCapture() {}, hasPointerCapture: () => true,
    releasePointerCapture: pointer => { position.released = pointer; } };
  const event = { currentTarget: group, pointerId: 3, preventDefault() {}, stopPropagation() {} };
  binding(line, '@pointerdown')(event);
  timers.tick(1000);
  return { event, text, position, assertRestored, lines, original, move: price => {
    const { scaleMin, scaleRange, padT, plotH } = card._thresholdDrag.scale;
    card._onThresholdPointerMove({ ...event, clientY: padT + plotH - (price - scaleMin) / scaleRange * plotH });
  } };
}

for (const [type, cutoff, delta, shown] of [
  ['charge', 20.02, 4, 20.13], ['charge', 24.5, -.25, 24.38], ['charge', -9, 30, -5.87], ['charge', 40, -10, 34.13],
  ['discharge', -3.02, 5, -3.13], ['discharge', -9.5, -1.25, -9.38], ['discharge', 24, 30, 21.87], ['discharge', -20, -10, -18.13],
]) {
  test(`relative ${type} drag at ${cutoff} snaps/clamps the signed delta ${delta} before deriving cutoff`, t => {
    t.mock.timers.enable({ apis: ['setTimeout'] });
    const result = relativeSetup(), { card, calls, prefix } = result;
    // Widen the displayed chart so drag targets can exceed the allowed delta range in both directions.
    result.states[`sensor.${prefix}_charge_plan`].attributes.plan[0].price = -20;
    result.states[`sensor.${prefix}_charge_plan`].attributes.plan[1].price = 40;
    const drag = startThresholdDrag(result, type, t.mock.timers);
    drag.move(cutoff);
    assert.equal(card._thresholdDrag.value, delta);
    assert.ok(Math.abs(card._thresholdDrag.price - shown) < 1e-8);
    assert.equal(drag.text.nodeValue, String(Math.round(shown * 10) / 10));
    card._onThresholdPointerUp(drag.event);
    assert.equal(card._thresholdDrag, null);
    assert.equal(drag.position.released, 3);
    assert.equal(card._pendingThresholds[type], delta, 'pending remains in delta units');
    assert.deepEqual(plain(calls), [['number', 'set_value', { entity_id: `number.${prefix}_${type}_price_threshold`, value: delta }]]);
    const displayed = chartCutoffs(result).filter(([kind]) => kind === type);
    assert.deepEqual(displayed, [[type, Math.round(shown * 10) / 10], [type, Math.round(shown * 10) / 10]]);
  });
}

for (const path of ['render', 'move', 'commit']) for (const change of ['mode', 'minimum', 'maximum', 'missing']) {
  test(`relative drag cancels on changed ${change} through ${path} without committing`, t => {
    t.mock.timers.enable({ apis: ['setTimeout'] });
    const result = relativeSetup(), { card, states, prefix, calls } = result;
    const drag = startThresholdDrag(result, 'charge', t.mock.timers);
    drag.move(10);
    assert.notDeepEqual(drag.lines.map(line => line.attributes), drag.original.lines);
    const attrs = states[`sensor.${prefix}_charge_plan`].attributes;
    if (change === 'mode') states[`switch.${prefix}_relative_auto_mode`].state = 'off';
    if (change === 'minimum') attrs.price_reference_min = -9;
    if (change === 'maximum') attrs.price_reference_max = 24.14;
    if (change === 'missing') attrs.price_reference_max = null;
    if (path === 'render') card.render();
    if (path === 'move') drag.move(21);
    if (path === 'commit') card._onThresholdPointerUp(drag.event);
    assert.equal(card._thresholdDrag, null);
    assert.equal(card._thresholdHoldTimer, null);
    assert.equal(drag.position.released, 3);
    drag.assertRestored();
    assert.equal(calls.length, 0);
    assert.deepEqual(plain(card._pendingThresholds), {});
  });
}

test('threshold pointer cancellation and missing references never commit or start a hold', t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const result = relativeSetup(), { card, states, prefix, calls } = result;
  const drag = startThresholdDrag(result, 'charge', t.mock.timers);
  drag.move(20);
  card._onThresholdPointerUp({ ...drag.event, type: 'pointercancel' });
  drag.assertRestored();
  card.render();
  drag.assertRestored();
  assert.equal(card._thresholdDrag, null);
  assert.equal(calls.length, 0);
  states[`sensor.${prefix}_charge_plan`].attributes.price_reference_max = null;
  card._onThresholdPointerDown(drag.event, 'charge', {});
  assert.equal(card._thresholdDrag, null);
  assert.equal(card._thresholdHoldTimer, null);
});

for (const state of ['unknown', 'unavailable']) {
  test(`relative lines ignore stale attributes on ${state} Charge Plan`, () => {
    const result = relativeSetup();
    result.states[`sensor.${result.prefix}_charge_plan`].state = state;
    assert.deepEqual(chartCutoffs(result), []);
  });
}

test('each relative cutoff requires its corresponding reference', () => {
  const result = relativeSetup(), attrs = result.states[`sensor.${result.prefix}_charge_plan`].attributes;
  attrs.price_reference_max = null;
  assert.deepEqual(chartCutoffs(result), [['discharge', -2.1], ['discharge', -2.1]]);
  attrs.price_reference_max = 24.13;
  attrs.price_reference_min = null;
  assert.deepEqual(chartCutoffs(result), [['charge', 20.1], ['charge', 20.1]]);
});

for (const type of ['charge', 'discharge']) {
  test(`absolute ${type} drag keeps absolute step snapping, service units and optimistic lines`, t => {
    t.mock.timers.enable({ apis: ['setTimeout'] });
    const result = relativeSetup('off'), { card, calls, prefix } = result;
    const drag = startThresholdDrag(result, type, t.mock.timers);
    drag.move(7.11);
    card._onThresholdPointerUp(drag.event);
    assert.equal(card._pendingThresholds[type], 7);
    assert.deepEqual(plain(calls), [['number', 'set_value', { entity_id: `number.${prefix}_${type}_price_threshold`, value: 7 }]]);
    assert.deepEqual(chartCutoffs(result).filter(([kind]) => kind === type), [[type, 7], [type, 7]]);
  });
}

test('absolute drag cannot commit after relative mode is enabled before rerender', t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const result = relativeSetup('off'), { card, states, prefix, calls } = result;
  const drag = startThresholdDrag(result, 'discharge', t.mock.timers);
  drag.move(7);
  states[`switch.${prefix}_relative_auto_mode`].state = 'on';
  card._onThresholdPointerUp(drag.event);
  drag.assertRestored();
  assert.equal(card._thresholdDrag, null);
  assert.equal(calls.length, 0);
  assert.deepEqual(plain(card._pendingThresholds), {});
});

for (const mode of ['on', 'off']) for (const type of ['charge', 'discharge']) for (const path of ['render', 'move', 'commit']) {
  test(`${type} threshold state change cancels through ${path} with relative mode ${mode}`, t => {
    t.mock.timers.enable({ apis: ['setTimeout'] });
    const result = relativeSetup(mode), { card, states, prefix, calls } = result;
    const drag = startThresholdDrag(result, type, t.mock.timers);
    drag.move(10);
    states[`number.${prefix}_${type}_price_threshold`].state = '5';
    if (path === 'render') card.render();
    if (path === 'move') drag.move(11);
    if (path === 'commit') card._onThresholdPointerUp(drag.event);
    assert.equal(card._thresholdDrag, null);
    assert.equal(card._thresholdHoldTimer, null);
    drag.assertRestored();
    assert.equal(calls.length, 0);
    assert.deepEqual(plain(card._pendingThresholds), {});
  });
}

for (const mode of ['on', 'off']) for (const type of ['charge', 'discharge']) {
  test(`explicit ${type} drag cancellation restores SVG coordinates and label with relative mode ${mode}`, t => {
    t.mock.timers.enable({ apis: ['setTimeout'] });
    const result = relativeSetup(mode), { card, calls } = result;
    const drag = startThresholdDrag(result, type, t.mock.timers);
    drag.move(10);
    assert.notDeepEqual(drag.lines.map(line => line.attributes), drag.original.lines);
    card._finishThresholdDrag(false);
    drag.assertRestored();
    card.render();
    drag.assertRestored();
    assert.equal(calls.length, 0);
  });
}

test('configured power and idle ranges reach Settings sliders and their help after reload', () => {
  const { card, templates, states, prefix } = setup();
  card.setConfig({ ...card.config, view: 'settings' });
  states[`switch.${prefix}_grid_feed_in_control`] = { state: 'on', attributes: {} };
  const settings = [
    ['charge_power', 'Charge Power'], ['discharge_power', 'Discharge Power'],
    ['min_grid_setpoint', 'Min Grid Setpoint'], ['max_grid_setpoint', 'Max Grid Setpoint'],
    ['default_max_grid_feed_in', 'Default Max Feed-in'],
    ['reduced_max_grid_feed_in', 'Reduced Max Feed-in'], ['idle_setpoint', 'Idle Setpoint'],
  ];
  for (const [power, idle] of [[27000, 1700], [1201, 0]]) {
    for (const [key, label] of settings) {
      const min = key === 'idle_setpoint' ? -idle : key === 'min_grid_setpoint' ? -power : 0;
      const max = key === 'idle_setpoint' ? idle : key === 'min_grid_setpoint' ? 0 : power;
      const step = key === 'idle_setpoint' ? 10 : 100;
      states[`number.${prefix}_${key}`] = { state: '0', attributes: { min, max, step } };
      templates.length = 0;
      card.render();
      const slider = ranges(templates).find(node => binding(node, 'aria-label') === label);
      for (const [name, value] of Object.entries({ min, max, step })) assert.equal(binding(slider, name), value);
      card._helpOpen = true;
      card._helpTopic = { key, label, unit: ' W' };
      const help = card._renderHelpDialog('settings', 'Settings');
      for (const [name, value] of [['Minimum', min], ['Maximum', max], ['Step', step]]) {
        assert.ok(help.includes(`<dt>${name}</dt><dd>${value} W</dd>`), `${key} ${name}`);
      }
    }
  }
});
