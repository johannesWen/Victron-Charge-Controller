const HOUR = 3600000;
const numeric = value => typeof value === 'number' && Number.isFinite(value);
const timestamp = value => typeof value === 'string' && /(?:Z|[+-]\d\d:\d\d)$/.test(value) ? Date.parse(value) : NaN;
const formatters = new Map();

function formatter(locale, options) {
  const key = JSON.stringify([locale, options]);
  if (!formatters.has(key)) {
    const value = new Intl.DateTimeFormat(locale, options);
    if (formatters.size >= 32) formatters.delete(formatters.keys().next().value);
    formatters.set(key, value);
  }
  return formatters.get(key);
}

export function normalizeForecast(data) {
  if (!data?.usable) return { usable: false, reason: data?.reason || 'PV forecast unavailable' };
  try {
    formatter('en', { timeZone: data.time_zone }).format();
    if (!data.time_zone || data.days?.length !== 2 || !Array.isArray(data.intervals)) throw new Error();
    const days = data.days.map(day => ({ ...day, start: timestamp(day.start), end: timestamp(day.end) }));
    if (days.some(day => !/^\d{4}-\d{2}-\d{2}$/.test(day.date) || !Number.isFinite(day.start) || !(day.end > day.start))
      || days[0].end !== days[1].start) throw new Error();
    const intervals = data.intervals.map(interval => ({ ...interval, start: timestamp(interval.start), end: timestamp(interval.end) }))
      .filter(interval => Number.isFinite(interval.start) && interval.end > interval.start && numeric(interval.pv_estimate) && interval.pv_estimate >= 0)
      .map(interval => ({ ...interval, pv_estimate10: numeric(interval.pv_estimate10) && interval.pv_estimate10 >= 0 ? interval.pv_estimate10 : null }))
      .sort((a, b) => a.start - b.start);
    if (!intervals.some(interval => interval.end > days[0].start && interval.start < days[1].end)) throw new Error();
    return { ...data, usable: true, days, intervals };
  } catch {
    return { usable: false, reason: 'Invalid PV forecast data' };
  }
}

export function localHour(time, timeZone) {
  return Number(formatter('en-GB', { timeZone, hour: '2-digit', hourCycle: 'h23' }).format(time));
}

export function forecastTime(time, timeZone) {
  return formatter('en-GB', { timeZone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'shortOffset' }).format(time);
}

export function normalizePlan(plan = []) {
  return plan.map(entry => ({ ...entry, start: timestamp(entry.start_time), end: timestamp(entry.end_time),
    price: numeric(entry.price) ? entry.price : null }));
}

export function buildForecastCharts(forecast, plan = []) {
  plan = normalizePlan(plan);
  const civilHour = formatter('en-GB', { timeZone: forecast.time_zone, hour: '2-digit', hourCycle: 'h23', timeZoneName: 'longOffset' });
  const minute = formatter('en-GB', { timeZone: forecast.time_zone, minute: '2-digit' });
  const days = forecast.days.map(day => {
    const entries = new Map(plan.filter(entry => entry.date === day.date).map(entry => [Number(entry.hour), entry]));
    let hours = [];
    let previousHour;
    // Split at civil-hour and offset changes, including partial DST hours.
    for (let start = day.start; start < day.end; start += HOUR / 60) {
      const key = civilHour.format(start);
      const end = Math.min(start + HOUR / 60, day.end);
      if (key === previousHour) hours.at(-1).end = end;
      else {
        const hour = localHour(start, forecast.time_zone);
        const entry = entries.get(hour);
        hours.push({ ...entry, date: day.date, start, end, hour, minute: Number(minute.format(start)), price: numeric(entry?.price) ? entry.price : null });
      }
      previousHour = key;
    }
    const periods = plan.filter(entry => Number.isFinite(entry.start) && entry.end > entry.start && entry.start < day.end && entry.end > day.start);
    if (plan.some(entry => Number.isFinite(entry.start))) {
      const boundaries = [...new Set([day.start, day.end,
        ...periods.flatMap(entry => [Math.max(day.start, entry.start), Math.min(day.end, entry.end)]),
        ...hours.map(hour => hour.start).filter(time => !periods.some(entry => entry.start < time && time < entry.end))])].sort((a, b) => a - b);
      hours = boundaries.slice(0, -1).map((start, index) => {
        const entry = periods.find(entry => entry.start <= start && start < entry.end);
        return { ...entry, date: day.date, start, end: boundaries[index + 1], hour: localHour(start, forecast.time_zone),
          minute: Number(minute.format(start)),
          price: entry?.price ?? null };
      });
    }
    const intervals = forecast.intervals.filter(interval => interval.start < day.end && interval.end > day.start)
      .map(interval => ({ ...interval, start: Math.max(day.start, interval.start), end: Math.min(day.end, interval.end) }));
    const boundaries = [...new Set([day.start, day.end, ...hours.flatMap(hour => [hour.start, hour.end]), ...intervals.flatMap(interval => [interval.start, interval.end])])].sort((a, b) => a - b);
    const slots = boundaries.slice(0, -1).map((start, index) => {
      const interval = intervals.find(interval => interval.start <= start && interval.end > start);
      const hourIndex = hours.findIndex(hour => hour.start <= start && start < hour.end);
      return { start, end: boundaries[index + 1], hourIndex, price: hours[hourIndex].price, pv_estimate: interval?.pv_estimate ?? null, pv_estimate10: interval?.pv_estimate10 ?? null };
    });
    const energy = key => intervals.length && intervals.every(interval => numeric(interval[key]))
      ? intervals.reduce((total, interval) => total + interval[key] * (interval.end - interval.start) / HOUR, 0)
      : null;
    return { ...day, hours, intervals, slots, pvKwh: energy('pv_estimate'), pv10Kwh: energy('pv_estimate10') };
  });
  const prices = days.flatMap(day => day.hours.map(hour => hour.price)).filter(numeric);
  const min = Math.min(0, ...prices), max = Math.max(0, ...prices);
  const margin = (max - min || 1) * 0.1;
  const pvMax = Math.max(1, ...days.flatMap(day => day.intervals.flatMap(interval => [interval.pv_estimate, interval.pv_estimate10 ?? 0])));
  // Reserve at least half the plot above zero for PV, even with negative-only prices.
  return { days, priceMin: min < 0 ? min - margin : 0, priceMax: Math.max(max, -min) + margin, pvMax: pvMax * 1.1 };
}

// Each missing value or timestamp gap starts a new area, so no curve bridges missing data.
export function forecastAreas(intervals, key, x, y, baseline) {
  const segments = [];
  let segment = [];
  for (const interval of intervals) {
    if (!numeric(interval[key]) || (segment.length && segment.at(-1).end !== interval.start)) {
      if (segment.length) segments.push(segment);
      segment = [];
    }
    if (numeric(interval[key])) segment.push(interval);
  }
  if (segment.length) segments.push(segment);
  return segments.map(items => {
    const first = items[0], last = items.at(-1);
    const points = [[first.start, first[key]], ...items.map(item => [(item.start + item.end) / 2, item[key]]), [last.end, last[key]]];
    return `M ${x(first.start)} ${baseline} L ${points.map(([time, value]) => `${x(time)} ${y(value)}`).join(' L ')} L ${x(last.end)} ${baseline} Z`;
  });
}

export class ForecastPoller {
  constructor(callWS, onState) {
    this.callWS = callWS;
    this.onState = onState;
    this.generation = 0;
    this.onReady = () => this.start();
    this.onDisconnected = () => this.pause('Home Assistant disconnected');
  }

  setActive(active, connection) {
    if (this.active === active && this.connection === connection) return;
    this.stop();
    this.active = active;
    this.connection = connection;
    if (!active) return;
    connection?.addEventListener?.('ready', this.onReady);
    connection?.addEventListener?.('disconnected', this.onDisconnected);
    if (connection?.connected !== false) this.start();
    else this.onState({ usable: false, reason: 'Home Assistant disconnected' });
  }

  start() {
    if (!this.active) return;
    clearInterval(this.timer);
    this.refresh();
    this.timer = setInterval(() => this.refresh(), 60000);
  }

  pause(reason) {
    clearInterval(this.timer);
    this.timer = null;
    this.generation++;
    this.onState({ usable: false, reason });
  }

  async refresh() {
    const generation = ++this.generation;
    try {
      const data = await this.callWS({ type: 'victron_charge_control/solar_forecast' });
      if (this.active && generation === this.generation) this.onState(normalizeForecast(data));
    } catch (error) {
      const reason = error?.code === 'unknown_command'
        ? 'Restart Home Assistant to load PV forecast support, then refresh the dashboard'
        : 'PV forecast unavailable (check integration support and connection)';
      if (this.active && generation === this.generation) this.onState({ usable: false, reason });
    }
  }

  stop() {
    clearInterval(this.timer);
    this.timer = null;
    this.generation++;
    this.connection?.removeEventListener?.('ready', this.onReady);
    this.connection?.removeEventListener?.('disconnected', this.onDisconnected);
    this.active = false;
  }
}
