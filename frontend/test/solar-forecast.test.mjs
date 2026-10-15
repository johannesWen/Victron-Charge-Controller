import assert from 'node:assert/strict';
import test from 'node:test';
import { normalizeForecast, buildForecastCharts, forecastAreas, forecastTime, ForecastPoller } from '../src/solar-forecast.mjs';

const HOUR = 3600000;
const fixture = (start = '2026-10-25T00:00:00+02:00', middle = '2026-10-26T00:00:00+01:00', end = '2026-10-27T00:00:00+01:00') => ({
  status: 'ready', usable: true, reason: null, source_updated_at: start, time_zone: 'Europe/Vienna',
  days: [{ date: start.slice(0, 10), start, end: middle }, { date: middle.slice(0, 10), start: middle, end }],
  intervals: [{ start, end: new Date(Date.parse(start) + HOUR / 2).toISOString(), pv_estimate: 0, pv_estimate10: null }],
});

test('DST fall-back uses 25 absolute hours and repeats the existing local-hour price', () => {
  const forecast = normalizeForecast(fixture());
  const charts = buildForecastCharts(forecast, [{ date: '2026-10-25', hour: 2, price: -5 }]);
  assert.equal(charts.days[0].hours.length, 25);
  assert.equal(charts.days[1].hours.length, 24);
  assert.equal(charts.days[0].end - charts.days[0].start, 25 * HOUR);
  const repeated = charts.days[0].hours.filter(hour => hour.hour === 2);
  assert.equal(repeated.length, 2);
  assert.deepEqual(repeated.map(hour => hour.price), [-5, -5]);
  assert.equal(repeated[1].start - repeated[0].start, HOUR);
  assert.notEqual(forecastTime(repeated[0].start, forecast.time_zone), forecastTime(repeated[1].start, forecast.time_zone));
});

test('DST spring-forward has 23 hours and no phantom hour', () => {
  const forecast = normalizeForecast(fixture('2026-03-29T00:00:00+01:00', '2026-03-30T00:00:00+02:00', '2026-03-31T00:00:00+02:00'));
  const day = buildForecastCharts(forecast).days[0];
  assert.equal(day.hours.length, 23);
  assert.equal(day.hours.some(hour => hour.hour === 2), false);
  assert.equal(day.date, '2026-03-29');
});

for (const [season, start, middle, end, expected] of [
  ['spring', '2026-10-04T00:00:00+10:30', '2026-10-05T00:00:00+11:00', '2026-10-06T00:00:00+11:00', [
    ['2026-10-04T01:00:00+10:30', 1, 60], ['2026-10-04T02:30:00+11:00', 2, 30], ['2026-10-04T03:00:00+11:00', 3, 60],
  ]],
  ['fall', '2026-04-05T00:00:00+11:00', '2026-04-06T00:00:00+10:30', '2026-04-07T00:00:00+10:30', [
    ['2026-04-05T01:00:00+11:00', 1, 60], ['2026-04-05T01:30:00+10:30', 1, 30], ['2026-04-05T02:00:00+10:30', 2, 60],
  ]],
]) test(`Lord Howe ${season} prices follow civil hours and the half-hour offset transition`, () => {
  const raw = { ...fixture(start, middle, end), time_zone: 'Australia/Lord_Howe' };
  const plan = Array.from({ length: 24 }, (_, hour) => ({ date: start.slice(0, 10), hour, price: hour }));
  const day = buildForecastCharts(normalizeForecast(raw), plan).days[0];
  assert.equal(day.hours.length, season === 'spring' ? 24 : 25);
  assert.deepEqual(day.hours.slice(1, 4).map(hour => [hour.start, hour.hour, (hour.end - hour.start) / 60000]),
    expected.map(([time, hour, minutes]) => [Date.parse(time), hour, minutes]));
  for (const hour of day.hours) {
    assert.equal(hour.price, hour.hour);
    assert.equal(day.slots.find(slot => slot.start === hour.start).price, hour.price);
    assert.equal(Number(new Intl.DateTimeFormat('en-GB', { timeZone: raw.time_zone, hour: '2-digit', hourCycle: 'h23' }).format(hour.end - 1)), hour.hour);
  }
});

test('shared scales include both days, negative prices and lower estimates; missing prices stay null', () => {
  const raw = fixture();
  raw.intervals.push({ start: raw.days[1].start, end: new Date(Date.parse(raw.days[1].start) + HOUR / 2).toISOString(), pv_estimate: 4, pv_estimate10: 6 });
  const charts = buildForecastCharts(normalizeForecast(raw), [
    { date: '2026-10-25', hour: 0, price: -12 },
    { date: '2026-10-26', hour: 0, price: 25 },
    { date: '2026-10-25', hour: 1, price: null },
    { date: '2026-10-25', hour: 3, price: undefined },
    { date: '2026-10-25', hour: 4, price: NaN },
  ]);
  assert.ok(charts.priceMin < -12);
  assert.ok(charts.priceMax > 25);
  assert.ok(charts.pvMax > 6);
  assert.equal(charts.days[0].hours.filter(hour => hour.price !== null).length, 1);
  assert.equal(charts.days[0].slots[0].pv_estimate, 0);
  assert.equal(charts.days[0].slots[0].pv_estimate10, null);
  assert.equal(charts.days[0].slots[1].pv_estimate, null);
});

test('zero production and missing prices still yield two charts with finite scales', () => {
  const charts = buildForecastCharts(normalizeForecast(fixture()));
  assert.equal(charts.days.length, 2);
  assert.equal(charts.days[0].intervals[0].end - charts.days[0].intervals[0].start, HOUR / 2);
  assert.ok(charts.pvMax > 0);
  assert.ok(charts.priceMax > charts.priceMin);
  assert.equal(charts.days[1].hours.every(hour => hour.price === null), true);
});

test('daily energy weights interval durations and clips at local midnight across DST', () => {
  const raw = fixture();
  raw.intervals = [
    { start: raw.days[0].start, end: raw.days[0].end, pv_estimate: 2, pv_estimate10: 1 },
    { start: raw.days[1].start, end: '2026-10-26T00:30:00+01:00', pv_estimate: 4, pv_estimate10: 2 },
    { start: '2026-10-26T23:45:00+01:00', end: '2026-10-27T00:15:00+01:00', pv_estimate: 8, pv_estimate10: 4 },
  ];
  const { days } = buildForecastCharts(normalizeForecast(raw));
  assert.deepEqual(days.map(day => [day.pv10Kwh, day.pvKwh]), [[25, 50], [2, 4]]);
});

test('daily energy distinguishes zero production, missing days and incomplete lower estimates', () => {
  const raw = fixture();
  let { days } = buildForecastCharts(normalizeForecast(raw));
  assert.equal(days[0].pvKwh, 0);
  assert.equal(days[0].pv10Kwh, null);
  assert.equal(days[1].pvKwh, null);
  assert.equal(days[1].pv10Kwh, null);
  raw.intervals.push({ start: '2026-10-25T00:30:00+02:00', end: '2026-10-25T01:00:00+02:00', pv_estimate: 4, pv_estimate10: 2 });
  ({ days } = buildForecastCharts(normalizeForecast(raw)));
  assert.equal(days[0].pvKwh, 2);
  assert.equal(days[0].pv10Kwh, null);
});

test('areas use straight lines, keep half-hour estimates and split on nulls or missing intervals', () => {
  const intervals = [
    { start: 0, end: 30, pv_estimate: 2, pv_estimate10: 1 },
    { start: 30, end: 60, pv_estimate: 4, pv_estimate10: null },
    { start: 60, end: 90, pv_estimate: 2, pv_estimate10: 1 },
    { start: 120, end: 150, pv_estimate: 0, pv_estimate10: 0 },
  ];
  const central = forecastAreas(intervals, 'pv_estimate', x => x, y => 10 - y, 10);
  const lower = forecastAreas(intervals, 'pv_estimate10', x => x, y => 10 - y, 10);
  assert.equal(central.length, 2);
  assert.equal(lower.length, 3);
  assert.match(central[0], /15 8 L 45 6 L 75 8/);
  assert.equal(central.some(path => /[CQ]/.test(path)), false);
  assert.match(lower[2], /^M 120 10 L 120 10/);
});

test('invalid contracts and naive times disable the view without turning null estimates into zero', () => {
  assert.equal(normalizeForecast({ usable: false, reason: 'not_configured' }).reason, 'not_configured');
  for (const change of [
    { time_zone: 'invalid/timezone' }, { days: [] }, { intervals: [] },
    { intervals: [{ start: '2026-10-25T12:00:00', end: '2026-10-25T12:30:00', pv_estimate: 3 }] },
    { intervals: [{ start: '2026-10-25T12:00:00Z', end: '2026-10-25T12:30:00Z', pv_estimate: null }] },
  ]) assert.equal(normalizeForecast({ ...fixture(), ...change }).usable, false);
});

function connection() {
  const handlers = new Map();
  return {
    connected: true, handlers,
    addEventListener(name, fn) { handlers.set(name, fn); },
    removeEventListener(name, fn) { if (handlers.get(name) === fn) handlers.delete(name); },
    emit(name) { handlers.get(name)?.(); },
  };
}
const flush = () => new Promise(resolve => setImmediate(resolve));

for (const failure of ['rejection', 'unusable']) test(`poller preserves cached PV state on re-entry until actual ${failure}`, async t => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  const requests = [], states = [], conn = connection();
  let mode = 'price';
  const poller = new ForecastPoller(() => new Promise((resolve, reject) => requests.push({ resolve, reject })), state => {
    states.push(state);
    if (!state.usable) mode = 'price';
  });
  t.after(() => poller.stop());
  poller.setActive(true, conn);
  assert.equal(states.length, 0);
  requests[0].resolve(fixture());
  await flush();
  mode = 'pv';
  const cached = states.at(-1);
  poller.setActive(false, conn);
  poller.setActive(true, conn);
  assert.equal(requests.length, 2);
  assert.equal(states.length, 1);
  assert.equal(states.at(-1), cached);
  assert.equal(mode, 'pv');
  requests[1].resolve(fixture());
  await flush();
  assert.equal(mode, 'pv');
  poller.stop();
  poller.setActive(true, conn);
  assert.equal(mode, 'pv');
  if (failure === 'rejection') requests[2].reject(new Error('connection failed'));
  else requests[2].resolve({ usable: false, reason: 'stale' });
  await flush();
  assert.equal(states.at(-1).usable, false);
  assert.equal(mode, 'price');
});

test('poller fetches only on entry/minute, ignores obsolete responses and cleans up listeners/timers', async t => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  const requests = [], states = [], conn = connection();
  const poller = new ForecastPoller(message => new Promise(resolve => requests.push({ message, resolve })), state => states.push(state));
  t.after(() => poller.stop());
  poller.setActive(true, conn);
  assert.equal(requests.length, 1);
  assert.deepEqual(requests[0].message, { type: 'victron_charge_control/solar_forecast' });
  poller.setActive(true, conn);
  assert.equal(requests.length, 1);
  t.mock.timers.tick(60000);
  assert.equal(requests.length, 2);
  requests[1].resolve(fixture());
  await flush();
  assert.equal(states.at(-1).usable, true);
  requests[0].resolve({ usable: false, reason: 'stale' });
  await flush();
  assert.equal(states.at(-1).usable, true);
  poller.setActive(false, conn);
  assert.equal(conn.handlers.size, 0);
  assert.equal(poller.timer, null);
  t.mock.timers.tick(60000);
  assert.equal(requests.length, 2);
});

test('disconnect falls back, rejects stale in-flight results and recovers on ready or re-entry', async t => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  const requests = [], states = [], conn = connection();
  const poller = new ForecastPoller(() => new Promise(resolve => requests.push(resolve)), state => states.push(state));
  t.after(() => poller.stop());
  poller.setActive(true, conn);
  conn.emit('disconnected');
  assert.equal(states.at(-1).usable, false);
  assert.equal(poller.timer, null);
  requests[0](fixture());
  await flush();
  assert.equal(states.at(-1).usable, false);
  conn.emit('ready');
  assert.equal(requests.length, 2);
  requests[1](fixture());
  await flush();
  assert.equal(states.at(-1).usable, true);
  poller.stop();
  poller.setActive(true, conn);
  assert.equal(requests.length, 3);
});

test('unknown command explains the required restart and a later poll can recover', async t => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  const states = [], conn = connection();
  let supported = false;
  const poller = new ForecastPoller(async () => { if (!supported) throw { code: 'unknown_command', message: 'Unknown command.' }; return fixture(); }, state => states.push(state));
  t.after(() => poller.stop());
  poller.setActive(true, conn);
  await flush();
  assert.equal(states.at(-1).usable, false);
  assert.equal(states.at(-1).reason, 'Restart Home Assistant to load PV forecast support, then refresh the dashboard');
  supported = true;
  t.mock.timers.tick(60000);
  await flush();
  assert.equal(states.at(-1).usable, true);
});
