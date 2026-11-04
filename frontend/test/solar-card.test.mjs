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
    LitElement: class { requestUpdate() {} disconnectedCallback() {} },
    document: { addEventListener() {}, removeEventListener() {} }, window: { addEventListener() {}, removeEventListener() {} },
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
  instance._tooltipHideTimer = setTimeout(() => assert.fail('tooltip timer survived'), 60000);
  instance.classList = { remove() {} };
  instance._thresholdDrag = { unlocked: true, price: 10, group: { classList: { remove() {} } } };
  instance._pickerBar = { index: 1 };
  instance._tooltipBar = { index: 1 };
  instance._setPlanChartMode('pv');
  assert.equal(instance._planChartMode, 'pv');
  for (const key of ['_thresholdHoldTimer', '_barHoldTimer', '_tooltipHideTimer', '_thresholdDrag', '_pickerBar', '_tooltipBar']) {
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
  assert.match(rendered, /No editable price intervals/);
  assert.equal((rendered.match(/Prices not yet available/g) || []).length, 2);
  assert.doesNotMatch(rendered, /class="plan-picker"|threshold-hit|Charge Threshold|_setPlanHourAction/);
  assert.match(rendered, /tabindex="0"/);
  assert.equal((rendered.match(/data-readonly=true/g) || []).length, 48);
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
    assert.ok(labels[0].rendered.includes(`>${String(target.hour).padStart(2, '0')}</text>`));
    const chart = charts.days.find(day => day.start <= Date.parse(now) && Date.parse(now) < day.end);
    const expectedX = 50 + (target.start - chart.start) / (chart.end - chart.start) * 500;
    assert.ok(markers[0].rendered.includes(`x="${expectedX}"`), 'outline belongs to the correct repeated hour');
  });
}

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

test('structured actions beat compact schedule states; structured arrays support plans without actions', () => {
  const instance = card(), plan = pricedPeriods();
  const values = { charge_hours: '2026-10-25:2', discharge_hours: '2026-10-25:2', pv_charge_hours: '2026-10-25:2' };
  instance._val = (_, key) => values[key];
  published(instance, plan, { charge_hours: [plan[0]], discharge_hours: [plan[1]], pv_charge_hours: [plan[3]] });
  assert.deepEqual(Array.from(instance._enrichPlanDisplayState(plan), period => period.displayAction), plan.map(period => period.action));
  const withoutActions = plan.map(({ action, ...period }) => period);
  assert.deepEqual(Array.from(instance._enrichPlanDisplayState(withoutActions), period => period.displayAction).slice(0, 4), ['charge', 'discharge', 'idle', 'pv_charge']);
});

function dayPlan(start, end, minutes = 15) {
  const date = start.slice(0, 10);
  return Array.from({ length: (Date.parse(end) - Date.parse(start)) / (minutes * 60000) }, (_, index) => {
    const time = Date.parse(start) + index * minutes * 60000;
    return { start_time: new Date(time).toISOString(), end_time: new Date(time + minutes * 60000).toISOString(),
      date, hour: forecast.localHour(time, 'Europe/Vienna'), minute: Number(new Intl.DateTimeFormat('en', { timeZone: 'Europe/Vienna', minute: '2-digit' }).format(time)),
      price: index % 4 + 1, action: 'idle' };
  });
}
function priceBars(rendered) {
  return [...rendered.matchAll(/<rect class="plan-price-bar"\s+x="([^"]+)" y="[^"]+" width="([^"]+)"/g)]
    .map(([, x, width]) => ({ x: Number(x), width: Number(width) }));
}

for (const [start, end, tomorrowEnd, count] of [
  ['2026-10-15T00:00:00+02:00', '2026-10-16T00:00:00+02:00', '2026-10-17T00:00:00+02:00', 96],
  ['2026-03-29T00:00:00+01:00', '2026-03-30T00:00:00+02:00', '2026-03-31T00:00:00+02:00', 92],
  ['2026-10-25T00:00:00+02:00', '2026-10-26T00:00:00+01:00', '2026-10-27T00:00:00+01:00', 100],
]) for (const view of ['price', 'pv']) test(`${view} fits all ${count} quarters into the day with four columns per hour`, () => {
  const templates = [], now = new Date(Date.parse(start) + 5.5 * 3600000).toISOString();
  const instance = card({ now, templates }), plan = dayPlan(start, end);
  published(instance, plan);
  const charts = chartsFor(plan, start, end, tomorrowEnd), day = charts.days[0];
  const rendered = view === 'price' ? instance._renderPriceChart(plan) : instance._renderSolarChart(day, charts, 'Europe/Vienna');
  assert.match(rendered, /viewBox="?0 0 600 280/);
  assert.doesNotMatch(rendered, /min-width:|plan-chart-scroll/);
  const bars = priceBars(rendered), plotWidth = view === 'price' ? 510 : 500;
  assert.equal(bars.length, count);
  assert.equal(new Set(bars.map(bar => bar.x)).size, count, 'DST quarters retain distinct positions');
  const targets = nodes(templates, 'plan-bar-group');
  assert.equal(targets.length, count / 4, 'one full-height target per actual hour');
  const widths = targets.map(node => Number(node.rendered.match(/width="?([\d.]+)/)[1]));
  assert.ok(widths.every(width => Math.abs(width - plotWidth / (count / 4)) < 1e-7));
  assert.ok(bars.every(bar => bar.width > 0 && bar.x >= 50 && bar.x + bar.width <= 50 + plotWidth));
  for (let index = 0; index < count; index += 4) {
    const hourBars = bars.slice(index, index + 4);
    assert.equal(hourBars.length, 4);
    const gaps = hourBars.slice(1).map((bar, offset) => bar.x - hourBars[offset].x - hourBars[offset].width);
    assert.ok(gaps.every(gap => Math.abs(gap - 0.5) < 1e-7), 'quarters have smaller intra-hour gaps');
    if (index) assert.ok(Math.abs(hourBars[0].x - bars[index - 1].x - bars[index - 1].width - 2) < 1e-7, 'hour blocks have normal 2-unit spacing');
  }
  const labels = templates.filter(node => node.strings.join('').includes('class="plan-axis-label '));
  assert.equal(labels.filter(node => node.rendered.includes('plan-current-hour')).length, 1);
  assert.ok(labels.length <= Math.ceil(count / 8) + 1, 'hour labels stay sparse');
  for (const label of labels) assert.match(label.rendered, />\d{2}<\/text>/);
  const current = labels.find(node => node.rendered.includes('plan-current-hour'));
  const currentHourStart = Date.parse(start) + 5 * 3600000;
  const center = 50 + (currentHourStart + 1800000 - Date.parse(start)) / (Date.parse(end) - Date.parse(start)) * plotWidth;
  const labelX = Number(current.rendered.match(/<text x="?([\d.]+)/)[1]);
  assert.ok(Math.abs(labelX - center) < 1e-7, 'current label is centered on the full hour');
});

for (const view of ['price', 'pv']) test(`${view} native hourly day keeps the old full-width bars`, () => {
  const instance = card(), start = '2026-10-15T00:00:00+02:00', end = '2026-10-16T00:00:00+02:00';
  const plan = dayPlan(start, end, 60), charts = chartsFor(plan, start, end, '2026-10-17T00:00:00+02:00');
  const rendered = view === 'price' ? instance._renderPriceChart(plan) : instance._renderSolarChart(charts.days[0], charts, 'Europe/Vienna');
  const bars = priceBars(rendered);
  assert.equal(bars.length, 24);
  assert.ok(bars.every(bar => Math.abs(bar.width - ((view === 'price' ? 510 : 500) / 24 - 2)) < 1e-7));
});

test('mixed price/PV charts keep elapsed-time widths and missing gaps within the full day', () => {
  const instance = card(), start = '2026-10-25T00:00:00+02:00', end = '2026-10-26T00:00:00+01:00';
  const plan = dayPlan(start, end);
  // Preserve four quarters, one hourly interval, then a gap before the remaining quarters.
  plan[4].end_time = plan[7].end_time;
  plan.splice(5, 4);
  const charts = chartsFor(plan);
  for (const view of ['price', 'pv']) {
    const rendered = view === 'price' ? instance._renderPriceChart(plan) : instance._renderSolarChart(charts.days[0], charts, 'Europe/Vienna');
    const bars = priceBars(rendered), unit = (view === 'price' ? 510 : 500) / 100;
    assert.equal(bars.length, 96);
    assert.ok(Math.abs((bars[4].width + 2) / unit - 4) < 1e-7, 'hourly interval keeps four times the quarter width');
    assert.ok(bars[5].x - bars[4].x - bars[4].width > unit, 'missing quarter stays an elapsed-time gap');
  }
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

test('History retains click-to-toggle tooltips', t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const instance = card();
  instance._onBarClick(event(), 'history', 0);
  assert.equal(instance._tooltipBar?.index, 0);
  instance._onBarClick(event(), 'history', 0);
  assert.equal(instance._tooltipBar, null);
  assert.equal(instance._tooltipHideTimer, null);
});

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


function openHour(instance, plan = pricedPeriods(), index = 0, view = 'price', templates = []) {
  published(instance, plan);
  let chartId = 'today';
  if (view === 'price') instance._renderPriceChart(plan);
  else {
    const charts = chartsFor(plan), day = charts.days[0];
    instance._renderSolarChart(day, charts, 'Europe/Vienna');
    chartId = `solar-${day.date}`;
    index = plan[index].start_time ? day.hours.findIndex(entry => entry.start_time === plan[index].start_time) : day.hours.findIndex(entry => entry.hour === plan[index].hour);
  }
  instance._openPicker(chartId, index);
  return instance._pickerBar;
}

for (const view of ['price', 'pv']) for (const gesture of ['click', 'contextmenu', 'pointerdown', 'keydown']) {
  test(`${view} ${gesture} selects a whole hour with four available quarters`, t => {
    t.mock.timers.enable({ apis: ['setTimeout'] });
    const templates = [], instance = card({ templates }), plan = pricedPeriods();
    openHour(instance, plan, 0, view);
    instance._closePicker();
    const targets = nodes(templates, 'plan-bar-group');
    const target = view === 'price' ? targets[0] : targets.find(node => node.rendered.includes('02:00 GMT+2–02:00 GMT+1'));
    assert.ok(target);
    handler(target, gesture)(event({}, { key: 'Enter', button: 0, clientX: 20, clientY: 30 }));
    if (gesture === 'pointerdown') t.mock.timers.tick(500);
    assert.equal(instance._pickerBar.rows.length, 4);
    assert.equal(instance._pickerBar.selected.size, 4);
    assert.equal(instance._pickerBar.group.start, Date.parse(plan[0].start_time));
    instance._renderPlanPicker();
    assert.equal(nodes(templates, 'plan-picker-period').length, 4);
    assert.equal(nodes(templates, 'plan-picker-btn').length, 4);
    assert.doesNotMatch(view === 'price' ? instance._renderPriceChart(plan) : '', /role="dialog"/);
    t.mock.timers.tick(60000);
    assert.ok(instance._pickerBar, 'selection has no inactivity timeout');
    instance._closePicker();
  });
}

for (const view of ['price', 'pv']) test(`${view} all four source columns open the same hour, folds stay separate`, () => {
  const instance = card(), plan = pricedPeriods();
  for (let index = 0; index < 8; index++) {
    const picker = openHour(instance, plan, index, view);
    assert.equal(picker.group.start, Date.parse(plan[index < 4 ? 0 : 4].start_time));
    assert.equal(picker.selected.size, 4);
    assert.ok(picker.rows.every(row => row.start >= picker.group.start && row.end <= picker.group.end));
    assert.match(instance._periodLabel(picker.group), index < 4 ? /GMT\+2/ : /GMT\+1/);
    instance._closePicker();
  }
});

for (const action of ['charge', 'pv_charge', 'discharge', 'idle']) for (const count of [1, 2, 4]) {
  test(`apply ${action} sends exactly ${count} selected quarter payloads`, async () => {
    const instance = card(), plan = pricedPeriods(), picker = openHour(instance, plan, 5);
    const calls = [];
    instance.hass.callService = (...args) => { calls.push(args); return Promise.resolve(); };
    picker.rows.slice(count).forEach(row => instance._togglePickerPeriod(row));
    assert.equal(calls.length, 0, 'selection does not write');
    await instance._applyPickerAction(action);
    assert.deepEqual(calls.map(([, service, data]) => [service, data.start_time, data.action]),
      plan.slice(4, 4 + count).map(row => ['set_slot_action', row.start_time, action]));
    assert.equal(instance._pickerBar, null);
    assert.equal(openHour(instance, plan, 5).selected.size, 4, 'reopening resets selection');
    instance._closePicker();
  });
}

test('zero selection disables modes and sends nothing', async () => {
  const templates = [], instance = card({ templates }), picker = openHour(instance);
  picker.rows.forEach(row => instance._togglePickerPeriod(row));
  instance._renderPlanPicker();
  assert.ok(nodes(templates, 'plan-picker-btn').every(node => node.rendered.includes('?disabled=true')));
  await instance._applyPickerAction('charge');
  assert.equal(instance._pickerBar.selected.size, 0);
  instance._closePicker();
});

test('current hour shows past and missing quarters disabled while current partial quarter is editable', () => {
  const templates = [], instance = card({ now: '2026-10-25T02:20:00+02:00', templates }), plan = pricedPeriods();
  plan[2].price = null;
  const picker = openHour(instance, plan);
  assert.equal(picker.rows.length, 4);
  assert.equal(picker.selected.size, 2);
  instance._renderPlanPicker();
  const buttons = nodes(templates, 'plan-picker-period');
  assert.match(buttons[0].rendered, /disabled=true[\s\S]*Past/);
  assert.match(buttons[1].rendered, /disabled=false/);
  assert.match(buttons[2].rendered, /disabled=true[\s\S]*Price unavailable/);
  // Missing source rows are visible placeholders, never independently editable.
  plan.splice(2, 1);
  assert.equal(openHour(instance, plan).rows.length, 4);
  assert.equal(instance._pickerBar.selected.size, 2);
  instance._closePicker();
});

test('apply revalidates latest prices, expiry, removed periods and changed boundaries without selecting replacements', async () => {
  let now = '2026-10-25T02:14:59+02:00';
  const instance = card({ now: () => now }), plan = pricedPeriods();
  openHour(instance, plan);
  const latest = plan.map(row => ({ ...row }));
  latest[1].price = null;
  latest[2].end_time = latest[3].end_time;
  now = '2026-10-25T02:15:00+02:00';
  published(instance, latest);
  instance._renderPriceChart(latest);
  const calls = [];
  instance.hass.callService = (_, service, data) => { calls.push([service, data.start_time]); };
  await instance._applyPickerAction('charge');
  assert.deepEqual(calls, [['set_slot_action', plan[3].start_time]]);
  assert.equal(instance._pickerBar.selected.size, 0);
  assert.match(instance._pickerBar.result, /1 of 4 intervals updated. 3 unavailable; 0 failed/);
  instance._closePicker();
});

test('late source update before rerender is revalidated; inserting an earlier period never changes selection', async () => {
  const instance = card(), plan = pricedPeriods();
  const picker = openHour(instance, plan, 1);
  picker.rows.slice(1).forEach(row => instance._togglePickerPeriod(row));
  const latest = [{ ...plan[0], start_time: '2026-10-24T23:45:00Z', end_time: plan[0].start_time }, ...plan];
  instance._renderPriceChart(latest);
  const calls = [];
  instance.hass.callService = (_, service, data) => calls.push(data.start_time);
  await instance._applyPickerAction('charge');
  assert.deepEqual(calls, [plan[0].start_time]);
  openHour(instance, plan);
  published(instance, plan.map(row => ({ ...row, price: null })));
  await instance._applyPickerAction('charge');
  assert.equal(calls.length, 1);
  instance._state = () => ({ attributes: {} });
  assert.equal(instance._currentPickerPeriod(instance._pickerBar.rows[0]), null, 'unavailable published plan invalidates the selection');
  instance._closePicker();
});

for (const view of ['price', 'pv']) test(`${view} native hourly feed stays one exact interval; legacy input uses the hour service`, async () => {
  const instance = card(), plan = dayPlan('2026-10-25T00:00:00+02:00', '2026-10-26T00:00:00+01:00', 60);
  let picker = openHour(instance, plan, 3, view);
  assert.equal(picker.rows.length, 1);
  const calls = [];
  instance.hass.callService = (_, service, data) => calls.push([service, data]);
  await instance._applyPickerAction('idle');
  assert.equal(calls[0][0], 'set_slot_action');
  assert.equal(calls[0][1].start_time, plan[3].start_time);
  const legacy = [{ date: '2026-10-25', hour: 2, price: 5 }];
  picker = openHour(instance, legacy, 0, view);
  // Legacy PV charts synthesize the two occurrences from the timestamp-free input.
  assert.equal(picker.rows.length, 1);
  await instance._applyPickerAction('charge');
  assert.equal(calls[1][0], 'set_hour_action');
});

test('mixed intervals retain actual bounds and source intervals spanning adjacent hours are unavailable', () => {
  const instance = card(), plan = pricedPeriods();
  plan[0].end_time = plan[1].end_time;
  plan.splice(1, 1);
  let picker = openHour(instance, plan);
  assert.equal(picker.rows.length, 3);
  assert.equal(picker.selected.size, 3);
  assert.match(instance._periodLabel(picker.rows[0]), /02:00 GMT\+2–02:30 GMT\+2/);
  const crossing = plan.map(row => ({ ...row }));
  crossing[2].end_time = crossing[3].end_time;
  picker = openHour(instance, crossing);
  assert.ok(picker.rows.every(row => row.start >= picker.group.start && row.end <= picker.group.end));
  assert.match(picker.rows[2].unavailableReason, /spans another hour/);
  const spanning = [{ ...plan[0], end_time: plan[4].end_time }];
  instance._closePicker();
  instance._renderPriceChart(spanning);
  instance._openPicker('today', 0);
  assert.equal(instance._pickerBar, null, 'an exact service cannot edit only part of a source interval');
});

test('partial failure rolls back only failed period, blocks duplicate apply, and does not retry siblings', async () => {
  const instance = card(), picker = openHour(instance), plan = pricedPeriods(), settles = [], calls = [];
  instance.hass.callService = (_, service, data) => { calls.push(data); return new Promise((resolve, reject) => settles.push({ resolve, reject })); };
  const applying = instance._applyPickerAction('discharge');
  await instance._applyPickerAction('charge');
  assert.equal(calls.length, 4);
  assert.equal(instance._pickerApplying, true);
  settles.forEach((settle, index) => index === 1 ? settle.reject(new Error('One quarter failed')) : settle.resolve());
  await applying;
  assert.equal(instance._pickerApplying, false);
  assert.equal(instance._pendingPlanActions[String(Date.parse(plan[1].start_time))], undefined);
  assert.equal(instance._pendingPlanActions[String(Date.parse(plan[0].start_time))].action, 'discharge');
  assert.match(picker.result, /3 of 4 intervals updated. 0 unavailable; 1 failed/);
  assert.equal(picker.selected.size, 0);
  await instance._applyPickerAction('discharge');
  assert.equal(calls.length, 4);
  assert.equal(instance._lastServiceError.message, 'One quarter failed');
  instance._closePicker();
});

test('dialog focuses a quarter, traps Tab, closes on Escape/outside/close and restores hour focus', async () => {
  const templates = [], instance = card({ templates }), plan = pricedPeriods();
  const focused = [], buttons = [0, 1, 2].map(index => ({ focus() { focused.push(index); } }));
  instance.updateComplete = Promise.resolve();
  instance.renderRoot = { querySelector: () => buttons[1], querySelectorAll: () => buttons, activeElement: buttons[2] };
  instance._renderPriceChart(plan);
  const trigger = { focus() { focused.push('hour'); }, dataset: {} };
  instance._onBarKeyDown(event({}, { key: 'Enter', currentTarget: trigger }), 'today', 0);
  await instance.updateComplete;
  assert.deepEqual(focused, [1]);
  instance._onPickerKeyDown(event({}, { key: 'Tab' }));
  assert.equal(focused.at(-1), 0);
  instance.renderRoot.activeElement = buttons[0];
  instance._onPickerKeyDown(event({}, { key: 'Tab', shiftKey: true }));
  assert.equal(focused.at(-1), 2);
  instance._onPickerKeyDown(event({}, { key: 'Escape' }));
  await instance.updateComplete;
  assert.equal(focused.at(-1), 'hour');
  assert.equal(instance._pickerBar, null);
  for (const close of ['outside', 'button']) {
    instance._openPicker('today', 0, trigger);
    templates.length = 0;
    instance._renderPlanPicker();
    if (close === 'outside') { const overlay = templates.at(-1), target = {}; handler(overlay, 'click')({ target, currentTarget: target }); }
    else {
      const close = templates.find(node => node.strings.join('').includes('aria-label="Close hour picker"'));
      const index = close.strings.findIndex(string => string.endsWith('@click=') && string.includes('Close hour picker'));
      close.values[index]();
    }
    assert.equal(instance._pickerBar, null);
  }
});

test('chart/page/config/disconnect cleanup closes picker and help never stacks with it', async () => {
  const instance = card();
  instance.updateComplete = Promise.resolve();
  openHour(instance);
  instance._openHelp();
  assert.equal(instance._pickerBar, null);
  instance._renderPriceChart(pricedPeriods());
  instance._openPicker('today', 0);
  assert.equal(instance._helpOpen, false);
  instance._openPlanPage(1);
  assert.equal(instance._pickerBar, null);
  openHour(instance);
  instance.setConfig({ view: 'settings' });
  assert.equal(instance._pickerBar, null);
  openHour(instance);
  instance._forecastPoller.stop = () => {};
  instance._finishThresholdDrag = () => {};
  instance.disconnectedCallback();
  assert.equal(instance._pickerBar, null);
});

for (const unavailable of ['past', 'missing']) test(`${unavailable} whole-hour targets block every editing gesture`, t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const templates = [], instance = card({ now: unavailable === 'past' ? '2026-10-26T00:00:00Z' : '2026-10-24T00:00:00Z', templates });
  const plan = pricedPeriods().map(row => ({ ...row, price: unavailable === 'missing' ? null : row.price }));
  const charts = chartsFor(plan);
  instance._renderSolarChart(charts.days[0], charts, 'Europe/Vienna');
  const target = nodes(templates, 'plan-bar-group').find(node => node.rendered.includes('02:00 GMT+2–02:00 GMT+1'));
  for (const gesture of ['click', 'contextmenu', 'pointerdown', 'keydown']) {
    handler(target, gesture)(event({ past: String(unavailable === 'past'), readonly: 'true' }, { key: 'Enter', button: 0 }));
    t.mock.timers.tick(500);
    assert.equal(instance._pickerBar, null);
    assert.equal(Object.keys(instance._pendingPlanActions).length, 0);
  }
});

for (const view of ['price', 'pv']) for (const unavailable of ['past', 'missing']) {
  for (const inspect of ['mouseenter', 'focus']) test(`${view} ${inspect} inspects all ${unavailable} hour details without enabling edits`, () => {
    const templates = [], instance = card({ now: unavailable === 'past' ? '2026-10-26T00:00:00Z' : '2026-10-24T00:00:00Z', templates });
    const plan = pricedPeriods();
    if (unavailable === 'missing') plan.slice(0, 4).forEach(entry => { entry.price = null; });
    published(instance, plan);
    const charts = chartsFor(plan), day = charts.days[0];
    const render = () => view === 'price' ? instance._renderPriceChart(plan) : instance._renderSolarChart(day, charts, 'Europe/Vienna');
    const initial = render();
    assert.doesNotMatch(initial, /class="plan-hour-tooltip"/);
    const target = nodes(templates, 'plan-bar-group').find(node => node.rendered.includes('02:00 GMT+2–02:00 GMT+1'));
    assert.ok(target);
    assert.match(target.rendered, /data-readonly=true/);
    for (const row of forecast.normalizePlan(plan).slice(0, 4)) {
      assert.ok(target.rendered.includes(instance._periodLabel(row)), 'accessible label and native title identify every actual interval');
      assert.ok(target.rendered.includes(row.price == null ? 'Price: unavailable' : `Price: ${row.price.toFixed(2)} ct/kWh`));
    }
    handler(target, inspect)(event());
    templates.length = 0;
    render();
    const tooltip = nodes(templates, 'plan-hour-tooltip')[0];
    assert.ok(tooltip);
    assert.match(tooltip.rendered, /pointer-events="none" aria-hidden="true"/);
    for (const row of forecast.normalizePlan(plan).slice(0, 4)) {
      assert.ok(tooltip.rendered.includes(instance._periodLabel(row)));
      assert.ok(tooltip.rendered.includes(row.price == null ? 'Price: unavailable' : `Price: ${row.price.toFixed(2)} ct/kWh`));
    }
    if (view === 'pv') {
      assert.match(tooltip.rendered, /PV: 2.00 kW/);
      assert.match(tooltip.rendered, /Lower: 1.00 kW/);
      assert.match(tooltip.rendered, /PV: unavailable/);
    }
    handler(target, 'click')(event());
    assert.equal(instance._pickerBar, null);
    assert.equal(Object.keys(instance._pendingPlanActions).length, 0);
    handler(target, inspect === 'focus' ? 'blur' : 'mouseleave')(event());
    assert.equal(instance._tooltipBar, null);
    assert.doesNotMatch(render(), /class="plan-hour-tooltip"/);
  });
}

test('opening an editable hour hides passive details and chart switching clears them', () => {
  const templates = [], instance = card({ templates }), plan = pricedPeriods();
  published(instance, plan);
  instance._renderPriceChart(plan);
  const target = nodes(templates, 'plan-bar-group')[0];
  handler(target, 'focus')(event());
  assert.match(instance._renderPriceChart(plan), /class="plan-hour-tooltip"/);
  handler(target, 'click')(event());
  assert.equal(instance._pickerBar.selected.size, 4);
  assert.doesNotMatch(instance._renderPriceChart(plan), /class="plan-hour-tooltip"/);
  instance._closePicker();
  handler(target, 'mouseenter')(event());
  instance._solarForecast = { usable: true };
  instance._setPlanChartMode('pv');
  assert.equal(instance._tooltipBar, null);
  assert.equal(instance._pickerBar, null);
});
