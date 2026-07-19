import { LitElement, html, svg, css, nothing } from 'lit';

// ────────────────────────────────────────────────────────────
// Constants
// ────────────────────────────────────────────────────────────

const CARD_VERSION = '0.1.0';
const CARD_TAG = 'victron-charge-controller-card';
const EDITOR_TAG = 'victron-charge-controller-card-editor';
const DEFAULT_PREFIX = 'victron_charge_control';

const CONTROL_MODES = ['off', 'auto', 'manual', 'force_charge', 'force_discharge'];

const MODE_META = {
  off:              { icon: 'mdi:power-off',                   label: 'Off' },
  auto:             { icon: 'mdi:auto-fix',                    label: 'Auto' },
  manual:           { icon: 'mdi:hand-back-right',             label: 'Manual' },
  force_charge:     { icon: 'mdi:battery-charging-high',       label: 'Force Charge' },
  force_discharge:  { icon: 'mdi:battery-arrow-down-outline',  label: 'Force Discharge' },
};

const ACTION_META = {
  idle:      { icon: 'mdi:pause-circle-outline', label: 'Idle' },
  charge:    { icon: 'mdi:battery-charging',     label: 'Charging' },
  pv_charge: { icon: 'mdi:solar-power-variant',  label: 'PV Charging' },
  discharge: { icon: 'mdi:battery-arrow-down',   label: 'Discharging' },
};

const FEED_IN_META = {
  default: { icon: 'mdi:transmission-tower',          label: 'Default' },
  reduced: { icon: 'mdi:transmission-tower-off',      label: 'Reduced' },
};

const HOURS = Array.from({ length: 24 }, (_, i) => i);

const COST_RANGES = {
  day:   { label: 'Day',   period: 'hour',  icon: 'mdi:calendar-today' },
  week:  { label: 'Week',  period: 'day',   icon: 'mdi:calendar-week' },
  month: { label: 'Month', period: 'day',   icon: 'mdi:calendar-month' },
  year:  { label: 'Year',  period: 'month', icon: 'mdi:calendar-range' },
};

// ────────────────────────────────────────────────────────────
// Main Card
// ────────────────────────────────────────────────────────────

class VictronChargeControllerCard extends LitElement {

  static get properties() {
    return {
      hass: { type: Object },
      config: { type: Object },
    };
  }

  constructor() {
    super();
    this._sliderHoldTimers = new WeakMap();
    this._sliderUnlocked = new WeakSet();
    // Threshold drag state
    this._thresholdDrag = null;
    this._thresholdHoldTimer = null;
    this._onThresholdPointerMoveBound = this._onThresholdPointerMove.bind(this);
    this._onThresholdPointerUpBound = this._onThresholdPointerUp.bind(this);
    this._onThresholdTouchMoveBound = this._onThresholdTouchMove.bind(this);
    // Pending threshold overrides (until HA entity catches up)
    this._pendingThresholds = {};
    this._costRange = 'day';
    this._costRangeOffsets = { day: 0, week: 0, month: 0, year: 0 };
    this._costMode = 'cost';
    this._costStatsState = { status: 'idle', key: null, points: [], error: null };
    this._tooltipBar = null;
    this._tooltipHideTimer = null;
    // Manual action picker state
    this._pickerBar = null;
    this._pickerHideTimer = null;
    this._barHoldTimer = null;
    this._barHoldStart = null;
    this._barLongPressFired = false;
    this._onDocumentPointerDownBound = this._onDocumentPointerDown.bind(this);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._finishThresholdDrag(false);
    if (this._tooltipHideTimer) clearTimeout(this._tooltipHideTimer);
    if (this._pickerHideTimer) clearTimeout(this._pickerHideTimer);
    if (this._barHoldTimer) {
      clearTimeout(this._barHoldTimer);
      this._barHoldTimer = null;
    }
    document.removeEventListener('pointerdown', this._onDocumentPointerDownBound, true);
  }

  // ── Lovelace lifecycle ──────────────────────────────────

  setConfig(config) {
    this.config = {
      view: 'settings',
      entity_prefix: DEFAULT_PREFIX,
      ...config,
    };
  }

  getCardSize() {
    return 12;
  }

  static getConfigElement() {
    return document.createElement(EDITOR_TAG);
  }

  static getStubConfig() {
    return { view: 'settings' };
  }

  // ── Entity helpers ──────────────────────────────────────

  _eid(domain, key) {
    return `${domain}.${this.config.entity_prefix}_${key}`;
  }

  _state(domain, key) {
    return this.hass?.states?.[this._eid(domain, key)];
  }

  _val(domain, key) {
    return this._state(domain, key)?.state;
  }

  _callService(domain, service, data) {
    return this.hass.callService(domain, service, data);
  }

  _callWS(message) {
    if (this.hass?.callWS) return this.hass.callWS(message);
    if (this.hass?.connection?.sendMessagePromise) {
      return this.hass.connection.sendMessagePromise(message);
    }
    return Promise.reject(new Error('Home Assistant WebSocket API is unavailable'));
  }

  _setNumber(key, value) {
    this._callService('number', 'set_value', {
      entity_id: this._eid('number', key),
      value: Number(value),
    });
  }

  _toggleSwitch(key) {
    const on = this._val('switch', key) === 'on';
    this._callService('switch', on ? 'turn_off' : 'turn_on', {
      entity_id: this._eid('switch', key),
    });
  }

  _selectMode(mode) {
    this._callService('select', 'select_option', {
      entity_id: this._eid('select', 'control_mode'),
      option: mode,
    });
  }

  _pressButton(key) {
    this._callService('button', 'press', {
      entity_id: this._eid('button', key),
    });
  }

  _setPlanHourAction(hour, action, date) {
    const data = { hour, action };
    if (date) data.date = date;
    this._callService('victron_charge_control', 'set_hour_action', data);
  }

  // ── Blocked-hours helpers ───────────────────────────────

  _parseHours(value) {
    if (!value || value === 'unknown' || value === 'unavailable') return [];
    return value
      .split(',')
      .map(s => parseInt(s.trim(), 10))
      .filter(n => !isNaN(n) && n >= 0 && n <= 23);
  }

  _parseScheduleSlots(value) {
    if (value === undefined || value === null || value === 'unknown' || value === 'unavailable') return null;
    const trimmed = String(value).trim();
    if (!trimmed) return new Set();

    const slots = new Set();
    for (const group of trimmed.split('|')) {
      const [date, hoursText, ...rest] = group.split(':');
      if (!date || hoursText === undefined || rest.length > 0) return null;
      const dateText = date.trim();
      if (!/^\d{4}-\d{2}-\d{2}$/.test(dateText)) return null;
      for (const rawHour of hoursText.split(',')) {
        const hourText = rawHour.trim();
        if (!hourText) continue;
        if (!/^\d+$/.test(hourText)) return null;
        const hour = Number.parseInt(hourText, 10);
        if (Number.isNaN(hour) || hour < 0 || hour > 23) return null;
        slots.add(`${dateText}:${hour}`);
      }
    }
    return slots;
  }

  _normalizePlanAction(action) {
    if (action === 'charge' || action === 'pv_charge' || action === 'discharge' || action === 'blocked') return action;
    return 'idle';
  }

  _enrichPlanDisplayState(plan) {
    const chargeSlots = this._parseScheduleSlots(this._val('sensor', 'charge_hours'));
    const dischargeSlots = this._parseScheduleSlots(this._val('sensor', 'discharge_hours'));
    const pvChargeSlots = this._parseScheduleSlots(this._val('sensor', 'pv_charge_hours'));
    const hasScheduleSensors = chargeSlots !== null && dischargeSlots !== null && pvChargeSlots !== null;
    const blockedChargingHours = this._parseHours(this._val('text', 'blocked_charging_hours'));
    const blockedDischargingHours = this._parseHours(this._val('text', 'blocked_discharging_hours'));

    return plan.map(entry => {
      const hour = entry.hour;
      const slotKey = entry.date !== undefined && hour !== undefined ? `${entry.date}:${hour}` : null;
      const blockedCharging = blockedChargingHours.includes(hour) || entry.action === 'blocked_charging' || entry.action === 'blocked';
      const blockedDischarging = blockedDischargingHours.includes(hour) || entry.action === 'blocked_discharging' || entry.action === 'blocked';

      let displayAction = this._normalizePlanAction(entry.action);
      // Per-day actions take precedence over recurring blocks (user override
      // via the plan-card picker). The blocked_*_hours flags are still used
      // for the hatched overlay so the user can see the hour is also blocked.
      if (hasScheduleSensors && slotKey) {
        // PV charge takes precedence over plain charge/discharge (matches backend).
        if (pvChargeSlots.has(slotKey)) displayAction = 'pv_charge';
        else if (chargeSlots.has(slotKey)) displayAction = 'charge';
        else if (dischargeSlots.has(slotKey)) displayAction = 'discharge';
        else if (blockedCharging && blockedDischarging) displayAction = 'blocked';
        else displayAction = 'idle';
      }

      return {
        ...entry,
        displayAction,
        blockedCharging,
        blockedDischarging,
      };
    });
  }

  _toggleBlockedHour(type, hour) {
    const key = type === 'charging'
      ? 'blocked_charging_hours'
      : 'blocked_discharging_hours';
    this._toggleHour(key, hour);
  }

  _toggleHour(key, hour) {
    const current = this._parseHours(this._val('text', key));
    const updated = current.includes(hour)
      ? current.filter(h => h !== hour)
      : [...current, hour].sort((a, b) => a - b);
    this._callService('text', 'set_value', {
      entity_id: this._eid('text', key),
      value: updated.join(', '),
    });
  }

  _extractEpexPrices(attrs, targetDate) {
    // Find the EPEX data list from entity attributes
    let rawData = null;
    if (Array.isArray(attrs.data) && attrs.data.length > 0) {
      rawData = attrs.data;
    } else {
      // Fallback: search for any list attribute with price-like dicts
      for (const [, val] of Object.entries(attrs)) {
        if (!Array.isArray(val) || val.length === 0) continue;
        const first = val[0];
        if (first && typeof first === 'object' && ('start_time' in first || 'price_ct_per_kwh' in first || 'price_per_kwh' in first)) {
          rawData = val;
          break;
        }
      }
    }
    if (!rawData) return {};

    const d = targetDate || new Date();
    const dateStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    const priceMap = {};
    for (const item of rawData) {
      const st = item.start_time;
      if (!st) continue;
      let dt;
      if (typeof st === 'string') {
        dt = new Date(st);
      } else if (st instanceof Date) {
        dt = st;
      } else {
        continue;
      }
      if (isNaN(dt.getTime())) continue;
      const itemDate = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
      if (itemDate !== dateStr) continue;
      // Extract price in ct/kWh
      let price = item.price_ct_per_kwh;
      if (price === undefined || price === null) {
        const priceEur = item.price_per_kwh;
        if (priceEur !== undefined && priceEur !== null) {
          price = parseFloat(priceEur) * 100;
        }
      }
      if (price !== undefined && price !== null) {
        priceMap[dt.getHours()] = parseFloat(price);
      }
    }
    return priceMap;
  }

  // ── Reusable render fragments ───────────────────────────

  _renderSection(title, icon, content) {
    return html`
      <div class="section">
        <div class="section-header">
          <ha-icon .icon=${icon}></ha-icon>
          <span>${title}</span>
        </div>
        <div class="section-content">${content}</div>
      </div>`;
  }

  _renderToggle(label, switchKey) {
    const on = this._val('switch', switchKey) === 'on';
    return html`
      <div class="control-row toggle-row">
        <span class="control-label">${label}</span>
        <ha-switch
          .checked=${on}
          @change=${() => this._toggleSwitch(switchKey)}
        ></ha-switch>
      </div>`;
  }

  _renderTogglePair(items) {
    return html`
      <div class="control-row toggle-pair">
        ${items.map(({ label, key }) => {
          const on = this._val('switch', key) === 'on';
          return html`
            <div class="toggle-pair-item">
              <span class="control-label">${label}</span>
              <ha-switch
                .checked=${on}
                @change=${() => this._toggleSwitch(key)}
              ></ha-switch>
            </div>
          `;
        })}
      </div>`;
  }

  _renderPlanControls() {
    const charge = this._state('switch', 'charge_allowed');
    const discharge = this._state('switch', 'discharge_allowed');
    if (!charge || !discharge) return nothing;

    const chargeOn = charge.state === 'on';
    const dischargeOn = discharge.state === 'on';

    return html`
      <div class="plan-controls">
        <div class="plan-control-toggle">
          <ha-icon icon="mdi:battery-plus"></ha-icon>
          <span class="plan-control-label">Charge allowed</span>
          <ha-switch
            .checked=${chargeOn}
            @change=${() => this._toggleSwitch('charge_allowed')}
          ></ha-switch>
        </div>
        <div class="plan-control-toggle">
          <ha-icon icon="mdi:battery-minus"></ha-icon>
          <span class="plan-control-label">Discharge allowed</span>
          <ha-switch
            .checked=${dischargeOn}
            @change=${() => this._toggleSwitch('discharge_allowed')}
          ></ha-switch>
        </div>
      </div>
    `;
  }

  _renderSlider(label, numberKey, unit = '') {
    const obj = this._state('number', numberKey);
    if (!obj) return nothing;
    const value = parseFloat(obj.state);
    const { min = 0, max = 100, step = 1 } = obj.attributes;
    return html`
      <div class="control-row slider-row">
        <span class="control-label">${label}</span>
        <div class="slider-wrap">
          <div class="slider-container">
            <input type="range"
              min=${min} max=${max} step=${step}
              .value=${String(value)}
              @input=${(e) => this._onSliderInput(e, unit)}
              @change=${(e) => this._onSliderChange(e, numberKey)}
              @pointerdown=${(e) => this._onSliderPointerDown(e)}
              @pointerup=${(e) => this._onSliderPointerUp(e)}
              @pointercancel=${(e) => this._onSliderPointerUp(e)}
            />
            <span class="slider-tooltip" style="display:none;"></span>
            <div class="slider-hold-progress"></div>
          </div>
          <span class="slider-value">${value}${unit}</span>
        </div>
      </div>`;
  }

  _onSliderPointerDown(e) {
    const input = e.target;
    // Store the original value to restore if not unlocked
    input.dataset.lockedValue = input.value;
    // Prevent the slider from moving until held long enough
    if (!this._sliderUnlocked.has(input)) {
      const progress = input.parentElement.querySelector('.slider-hold-progress');
      progress.classList.add('active');
      this._sliderHoldTimers.set(input, setTimeout(() => {
        this._sliderUnlocked.add(input);
        input.classList.add('unlocked');
        progress.classList.remove('active');
        progress.classList.add('done');
        // Brief haptic-like visual pulse
        input.parentElement.classList.add('slider-activated');
        setTimeout(() => input.parentElement.classList.remove('slider-activated'), 200);
      }, 1000));
    }
  }

  _onSliderPointerUp(e) {
    const input = e.target;
    const progress = input.parentElement.querySelector('.slider-hold-progress');
    // Clear pending hold timer
    const timer = this._sliderHoldTimers.get(input);
    if (timer) {
      clearTimeout(timer);
      this._sliderHoldTimers.delete(input);
    }
    progress.classList.remove('active', 'done');
    // If not unlocked, restore original value immediately
    if (!this._sliderUnlocked.has(input)) {
      if (input.dataset.lockedValue !== undefined) {
        input.value = input.dataset.lockedValue;
      }
    }
    // Don't re-lock here — let _onSliderChange commit first, then re-lock
  }

  _onSliderInput(e, unit) {
    const input = e.target;
    // If not unlocked, revert to locked value
    if (!this._sliderUnlocked.has(input)) {
      if (input.dataset.lockedValue !== undefined) {
        input.value = input.dataset.lockedValue;
      }
      return;
    }
    const tooltip = input.parentElement.querySelector('.slider-tooltip');
    const val = input.value;
    const min = parseFloat(input.min);
    const max = parseFloat(input.max);
    const pct = (val - min) / (max - min);
    tooltip.textContent = `${val}${unit}`;
    tooltip.style.display = 'block';
    tooltip.style.left = `calc(${pct * 100}% + ${(0.5 - pct) * 16}px)`;
  }

  _onSliderChange(e, numberKey) {
    const input = e.target;
    const tooltip = input.parentElement.querySelector('.slider-tooltip');
    tooltip.style.display = 'none';
    // Commit if the slider was unlocked, then re-lock
    if (this._sliderUnlocked.has(input)) {
      this._setNumber(numberKey, input.value);
      this._sliderUnlocked.delete(input);
      input.classList.remove('unlocked');
    } else if (input.dataset.lockedValue !== undefined) {
      input.value = input.dataset.lockedValue;
    }
  }

  // ── Threshold drag handlers ─────────────────────────────

  _svgYToPrice(svgY, scale) {
    const { scaleMin, scaleRange, padT, plotH } = scale;
    const clamped = Math.max(padT, Math.min(padT + plotH, svgY));
    return scaleMin + ((padT + plotH - clamped) / plotH) * scaleRange;
  }

  _clientToSvgY(clientY, svgEl) {
    const pt = svgEl.createSVGPoint();
    pt.x = 0;
    pt.y = clientY;
    const svgPt = pt.matrixTransform(svgEl.getScreenCTM().inverse());
    return svgPt.y;
  }

  _clientToSvgPoint(clientX, clientY, svgEl) {
    const pt = svgEl.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    const svgPt = pt.matrixTransform(svgEl.getScreenCTM().inverse());
    return { x: svgPt.x, y: svgPt.y };
  }

  _addThresholdDragListeners() {
    const opts = { passive: false, capture: true };
    document.addEventListener('pointermove', this._onThresholdPointerMoveBound, opts);
    document.addEventListener('pointerup', this._onThresholdPointerUpBound, opts);
    document.addEventListener('pointercancel', this._onThresholdPointerUpBound, opts);
    window.addEventListener('touchmove', this._onThresholdTouchMoveBound, opts);
  }

  _removeThresholdDragListeners() {
    document.removeEventListener('pointermove', this._onThresholdPointerMoveBound, true);
    document.removeEventListener('pointerup', this._onThresholdPointerUpBound, true);
    document.removeEventListener('pointercancel', this._onThresholdPointerUpBound, true);
    window.removeEventListener('touchmove', this._onThresholdTouchMoveBound, true);
  }

  _finishThresholdDrag(commit = true) {
    this._removeThresholdDragListeners();

    if (this._thresholdHoldTimer) {
      clearTimeout(this._thresholdHoldTimer);
      this._thresholdHoldTimer = null;
    }

    if (!this._thresholdDrag) return;
    const { type, unlocked, price, group, pointerId } = this._thresholdDrag;
    group.classList.remove('threshold-holding', 'threshold-unlocked');
    this.classList.remove('threshold-drag-active');

    if (pointerId !== undefined && group.hasPointerCapture) {
      try {
        if (group.hasPointerCapture(pointerId)) group.releasePointerCapture(pointerId);
      } catch (_err) {
        // Some mobile WebViews throw if the pointer has already been canceled.
      }
    }

    if (commit && unlocked && price !== null) {
      const key = type === 'charge' ? 'charge_price_threshold' : 'discharge_price_threshold';
      const rounded = Math.round(price * 100) / 100;
      this._setNumber(key, rounded);
      // Store pending value so both charts update immediately
      this._pendingThresholds[type] = rounded;
      this.requestUpdate();
    }

    this._thresholdDrag = null;
  }

  _onThresholdPointerDown(e, type, scale) {
    e.preventDefault();
    e.stopPropagation();
    if (this._thresholdDrag) this._finishThresholdDrag(false);

    const group = e.currentTarget;
    const svgEl = group.closest('svg');
    const pointerId = e.pointerId;

    // Start hold timer
    if (this._thresholdHoldTimer) clearTimeout(this._thresholdHoldTimer);
    this._thresholdDrag = { type, scale, group, svgEl, pointerId, unlocked: false, price: null };
    group.classList.add('threshold-holding');
    this.classList.add('threshold-drag-active');
    this._addThresholdDragListeners();

    if (group.setPointerCapture && pointerId !== undefined) {
      try {
        group.setPointerCapture(pointerId);
      } catch (_err) {
        // Pointer capture is best effort in embedded mobile WebViews.
      }
    }

    this._thresholdHoldTimer = setTimeout(() => {
      if (!this._thresholdDrag) return;
      this._thresholdDrag.unlocked = true;
      group.classList.remove('threshold-holding');
      group.classList.add('threshold-unlocked');
    }, 1000);
  }

  _onThresholdPointerMove(e) {
    if (!this._thresholdDrag) return;
    if (this._thresholdDrag.pointerId !== undefined && e.pointerId !== this._thresholdDrag.pointerId) return;
    e.preventDefault();
    e.stopPropagation();
    if (!this._thresholdDrag.unlocked) return;

    const { scale, group, svgEl } = this._thresholdDrag;
    const svgY = this._clientToSvgY(e.clientY, svgEl);
    let price = this._svgYToPrice(svgY, scale);
    // Snap to step
    price = Math.round(price / scale.step) * scale.step;
    price = Math.max(scale.scaleMin, Math.min(scale.scaleMax, price));
    this._thresholdDrag.price = price;

    // Update line and label position in DOM
    const yPos = scale.padT + scale.plotH - ((price - scale.scaleMin) / scale.scaleRange) * scale.plotH;
    const lines = group.querySelectorAll('line');
    lines.forEach(l => { l.setAttribute('y1', yPos); l.setAttribute('y2', yPos); });
    const label = group.querySelector('text');
    if (label) {
      label.setAttribute('y', yPos + 3.5);
      label.textContent = Math.round(price * 10) / 10;
    }
  }

  _onThresholdTouchMove(e) {
    if (!this._thresholdDrag) return;
    if (e.cancelable) e.preventDefault();
    e.stopPropagation();
  }

  _onThresholdPointerUp(e) {
    if (!this._thresholdDrag) return;
    if (this._thresholdDrag.pointerId !== undefined && e.pointerId !== this._thresholdDrag.pointerId) return;
    e.preventDefault();
    e.stopPropagation();
    this._finishThresholdDrag(true);
  }

  _renderHourChips({ key, activeClass = 'blocked', onClick }) {
    const selected = this._parseHours(this._val('text', key));
    const toggle = onClick ?? (h => this._toggleHour(key, h));
    return html`
      <div class="hour-grid">
        ${HOURS.map(h => html`
          <button
            class="hour-chip ${selected.includes(h) ? activeClass : ''}"
            @click=${() => toggle(h)}
          >${String(h).padStart(2, '0')}</button>
        `)}
      </div>`;
  }

  // ── Controls view ───────────────────────────────────────

  _renderControlsView() {
    const mode     = this._val('select', 'control_mode') || 'off';
    const action   = this._val('sensor', 'desired_action') || 'idle';
    const actMeta  = ACTION_META[action] || ACTION_META.idle;
    const setpoint = this._val('sensor', 'target_setpoint') || '0';
    const spotPrice = this._val('sensor', 'current_price');
    const isAuto   = mode === 'auto';
    const feedIn   = this._val('switch', 'grid_feed_in_control') === 'on';

    return html`
      <!-- Mode & Status -->
      ${this._renderSection('Mode', 'mdi:cog', html`
        <div class="mode-group">
          ${CONTROL_MODES.map(m => {
            const meta = MODE_META[m];
            return html`
              <button
                class="mode-btn ${mode === m ? 'active' : ''}"
                data-mode=${m}
                @click=${() => this._selectMode(m)}
                title=${meta.label}
              >
                <ha-icon .icon=${meta.icon}></ha-icon>
                <span class="mode-label">${meta.label}</span>
              </button>`;
          })}
        </div>
        <div class="status-row">
          <div class="status-item">
            <ha-icon .icon=${actMeta.icon}></ha-icon>
            <span>${actMeta.label}</span>
          </div>
          <div class="status-item">
            <ha-icon icon="mdi:flash"></ha-icon>
            <span>${setpoint} W</span>
          </div>
          <div class="status-item">
            <ha-icon icon="mdi:currency-eur"></ha-icon>
            <span>${spotPrice != null && spotPrice !== 'unavailable' && spotPrice !== 'unknown' ? `${(parseFloat(spotPrice) * 100).toFixed(2)} ct/kWh` : '—'}</span>
          </div>
        </div>
      `)}

      <!-- Charge / Discharge -->
      ${this._renderSection('Charge / Discharge', 'mdi:battery-charging', html`
        ${this._renderTogglePair([
          { label: 'Charge Allowed', key: 'charge_allowed' },
          { label: 'Discharge Allowed', key: 'discharge_allowed' },
        ])}
        ${this._renderSlider('Charge Power', 'charge_power', ' W')}
        ${this._renderSlider('Discharge Power', 'discharge_power', ' W')}
        ${this._renderSlider('PV Charging Battery Share', 'pv_charging_battery_share', ' %')}
      `)}

      <!-- Battery Limits -->
      ${this._renderSection('Battery Limits', 'mdi:battery-medium', html`
        ${this._renderSlider('Min SOC', 'min_soc', '%')}
        ${this._renderSlider('Max SOC', 'max_soc', '%')}
        ${this._renderSlider('SOC Hysteresis', 'soc_hysteresis', '%')}
      `)}

      <!-- Grid Settings -->
      ${this._renderSection('Grid Settings', 'mdi:transmission-tower', html`
        ${this._renderSlider('Idle Setpoint', 'idle_setpoint', ' W')}
        ${this._renderSlider('Min Grid Setpoint', 'min_grid_setpoint', ' W')}
        ${this._renderSlider('Max Grid Setpoint', 'max_grid_setpoint', ' W')}
      `)}

      <!-- Auto Mode (visible only when mode=auto) -->
      ${isAuto ? this._renderSection('Auto Mode', 'mdi:auto-fix', html`
        ${this._renderSlider('Cheapest Hours', 'cheapest_hours_auto_charge', ' h')}
        ${this._renderSlider('Expensive Hours', 'expensive_hours_auto_discharge', ' h')}
        ${this._renderSlider('Charge Price Threshold', 'charge_price_threshold', ' ct/kWh')}
        ${this._renderSlider('Discharge Price Threshold', 'discharge_price_threshold', ' ct/kWh')}
      `) : nothing}

      <!-- Grid Feed-in -->
      ${this._renderSection('Grid Feed-in', 'mdi:solar-power', html`
        ${this._renderTogglePair([
          { label: 'Feed-in Control', key: 'grid_feed_in_control' },
          { label: 'Control DC Coupled Feed In', key: 'control_dc_coupled_feed_in' },
        ])}
        ${feedIn ? html`
          ${this._renderSlider('Price Threshold', 'grid_feed_in_price_threshold', ' ct/kWh')}
          ${this._renderSlider('Default Max Feed-in', 'default_max_grid_feed_in', ' W')}
          ${this._renderSlider('Reduced Max Feed-in', 'reduced_max_grid_feed_in', ' W')}
        ` : nothing}
      `)}

      <!-- Blocked Hours -->
      ${this._renderSection('Blocked Hours', 'mdi:clock-alert', html`
        <div class="blocked-group">
          <span class="blocked-label">Charging</span>
          ${this._renderHourChips({ key: 'blocked_charging_hours', activeClass: 'blocked', onClick: h => this._toggleBlockedHour('charging', h) })}
        </div>
        <div class="blocked-group">
          <span class="blocked-label">Discharging</span>
          ${this._renderHourChips({ key: 'blocked_discharging_hours', activeClass: 'blocked', onClick: h => this._toggleBlockedHour('discharging', h) })}
        </div>
      `)}

      <!-- Replan Hours -->
      ${this._renderSection('Replan Hours', 'mdi:calendar-refresh', html`
        <div class="blocked-group">
          <span class="blocked-label">Recalculation Hours</span>
          ${this._renderHourChips({ key: 'replan_hours', activeClass: 'replan' })}
        </div>
      `)}

      <!-- Action buttons -->
      <div class="actions">
        <button class="action-btn primary"
          @click=${() => this._pressButton('recalculate_schedule')}>
          <ha-icon icon="mdi:refresh"></ha-icon>
          Recalculate
        </button>
        <button class="action-btn"
          @click=${() => this._callService('victron_charge_control', 'clear_schedule', {})}>
          <ha-icon icon="mdi:delete-outline"></ha-icon>
          Clear Schedule
        </button>
      </div>`;
  }

  // ── Shared chart renderer ────────────────────────────────

  _renderPriceChart(enrichedPlan, { showCurrentHour = false, chargeThreshold = null, dischargeThreshold = null, forcedScaleMin = null, forcedScaleMax = null, chartId = 'today' } = {}) {
    // Extract prices and determine scale
    const validPrices = enrichedPlan
      .map(p => p.price)
      .filter(p => p !== null && p !== undefined)
      .map(Number)
      .filter(Number.isFinite);
    if (validPrices.length === 0) return null;

    let scaleMin, scaleMax;
    if (forcedScaleMin !== null && forcedScaleMax !== null) {
      scaleMin = forcedScaleMin;
      scaleMax = forcedScaleMax;
    } else {
      const minPrice = Math.min(...validPrices);
      const maxPrice = Math.max(...validPrices);
      const priceRange = maxPrice - minPrice || 1;
      scaleMin = Math.min(-1, minPrice);
      scaleMax = Math.max(1, Math.ceil(maxPrice + priceRange * 0.1));
    }
    const scaleRange = scaleMax - scaleMin || 1;

    const currentHour = new Date().getHours();

    // SVG dimensions
    const chartW = 600;
    const chartH = 280;
    const padL = 50;
    const padR = 40;
    const padT = 38;
    const padB = 30;
    const plotW = chartW - padL - padR;
    const plotH = chartH - padT - padB;
    const barCount = enrichedPlan.length;
    const barW = plotW / barCount;
    const barGap = 2;

    const actionColor = (action) => {
      switch (action) {
        case 'charge':              return 'var(--vcc-success, #4caf50)';
        case 'pv_charge':           return 'var(--vcc-pv-charge, #ffb74d)';
        case 'discharge':           return '#ff6600';
        case 'blocked':             return 'var(--vcc-blocked-both, #f44336)';
        default:                    return 'var(--vcc-disabled, #bdbdbd)';
      }
    };

    const blockedOverlayFill = (entry) => {
      if (entry.blockedCharging && entry.blockedDischarging) return 'url(#plan-hatch-blocked-both)';
      if (entry.blockedCharging) return 'url(#plan-hatch-blocked-charging)';
      if (entry.blockedDischarging) return 'url(#plan-hatch-blocked-discharging)';
      return null;
    };

    const yPos = (price) => padT + plotH - ((price - scaleMin) / scaleRange) * plotH;
    const zeroInRange = scaleMin <= 0 && scaleMax >= 0;

    const tickCount = 5;
    const yTicks = Array.from({ length: tickCount + 1 }, (_, i) => {
      const val = scaleMin + (scaleRange * i) / tickCount;
      return { val: Math.round(val * 10) / 10, y: yPos(scaleMin + (scaleRange * i) / tickCount) };
    });

    return svg`
      <svg class="plan-chart" viewBox="0 0 ${chartW} ${chartH}" preserveAspectRatio="xMidYMid meet">
        <defs>
          <pattern id="plan-hatch-blocked-charging" patternUnits="userSpaceOnUse" width="10" height="10">
            <path d="M-2,12 L12,-2"
              stroke="var(--vcc-blocked-charging, #2e7d32)" stroke-width="1.8" opacity="0.95" />
          </pattern>
          <pattern id="plan-hatch-blocked-discharging" patternUnits="userSpaceOnUse" width="10" height="10">
            <path d="M-2,12 L12,-2"
              stroke="var(--vcc-blocked-discharging, #ef6c00)" stroke-width="1.8" opacity="0.95" />
          </pattern>
          <pattern id="plan-hatch-blocked-both" patternUnits="userSpaceOnUse" width="10" height="10">
            <path d="M-2,12 L12,-2"
              stroke="var(--vcc-bg, #fff)" stroke-width="1.8" opacity="0.95" />
          </pattern>
        </defs>

        <!-- Grid lines -->
        ${yTicks.map(t => svg`
          <line x1="${padL}" y1="${t.y}" x2="${chartW - padR}" y2="${t.y}"
            stroke="var(--vcc-border, #e0e0e0)" stroke-width="0.5"
            stroke-dasharray="${t.val === 0 ? 'none' : '4,3'}" />
        `)}

        <!-- Zero line (bold) -->
        ${zeroInRange ? svg`
          <line x1="${padL}" y1="${yPos(0)}" x2="${chartW - padR}" y2="${yPos(0)}"
            stroke="var(--vcc-text2, #757575)" stroke-width="1" />
        ` : nothing}

        <!-- Bars -->
        ${enrichedPlan.map((entry, i) => {
          const price = Number(entry.price);
          if (!Number.isFinite(price)) return nothing;
          const h = entry.hour ?? i;
          const x = padL + i * barW + barGap / 2;
          const w = barW - barGap;
          const colX = padL + i * barW;
          const colW = barW;
          const barTop = yPos(price);
          const barBase = zeroInRange ? yPos(0) : padT + plotH;
          const barY = Math.min(barTop, barBase);
          const barH = Math.abs(barTop - barBase) || 1;
          const isPast = showCurrentHour && h < currentHour;
          const isCurrent = showCurrentHour && h === currentHour;
          const displayAction = entry.displayAction || entry.action;
          const overlayFill = isPast ? null : blockedOverlayFill(entry);
          const isPvCharge = !isPast && displayAction === 'pv_charge';
          // Price bar stays grey on PV-charge hours; the light-orange background
          // column is the PV indicator (avoids confusion with the orange discharge bar).
          const barFillColor = isPast ? actionColor('idle') : (isPvCharge ? actionColor('idle') : actionColor(displayAction));
          return svg`
            <g class="plan-bar-group"
              data-past=${isPast ? 'true' : 'false'}
              @click=${(e) => this._onBarClick(e, chartId, i)}
              @contextmenu=${(e) => this._onBarContextMenu(e, chartId, i)}
              @pointerdown=${(e) => this._onBarPointerDown(e, chartId, i)}
              @pointermove=${(e) => this._onBarPointerMove(e)}
              @pointerup=${(e) => this._onBarPointerUp(e)}
              @pointercancel=${(e) => this._onBarPointerUp(e)}
              @pointerleave=${(e) => this._onBarPointerUp(e)}>
              <!-- Full-column transparent hit target so the whole time slot is
                   long-pressable/clickable even when the price bar is near zero. -->
              <rect class="plan-bar-hit"
                x="${colX}" y="${padT}" width="${colW}" height="${plotH}"
                fill="transparent" pointer-events="all" />
              ${isPvCharge ? svg`
                <!-- PV Charge background column (light orange) -->
                <rect class="plan-pv-column"
                  x="${colX}" y="${padT}" width="${colW}" height="${plotH}"
                  fill="var(--vcc-pv-charge, #ffb74d)" opacity="0.10" rx="1.5"
                  pointer-events="none" />
              ` : nothing}
              <rect
                x="${x}" y="${barY}" width="${w}" height="${barH}"
                fill="${barFillColor}"
                opacity="${isPast ? 0.35 : (isCurrent ? 1 : 0.7)}"
                rx="1.5"
              />
              ${overlayFill ? svg`
                <rect
                  x="${x}" y="${barY}" width="${w}" height="${barH}"
                  fill="${overlayFill}"
                  opacity="${isCurrent ? 1 : 0.9}"
                  rx="1.5"
                />
              ` : nothing}
              ${isCurrent ? svg`
                <rect x="${x - 1}" y="${padT}" width="${w + 2}" height="${plotH}"
                  fill="none" stroke="var(--vcc-accent, #03a9f4)"
                  stroke-width="1.5" stroke-dasharray="4,3" rx="2" />
              ` : nothing}
            </g>
          `;
        })}

        <!-- Y-axis labels -->
        ${yTicks.map(t => svg`
          <text x="${padL - 6}" y="${t.y + 3.5}" text-anchor="end"
            class="plan-axis-label">${t.val}</text>
        `)}

        <!-- Charge threshold line (interactive) -->
        ${chargeThreshold !== null && chargeThreshold >= scaleMin && chargeThreshold <= scaleMax ? (() => {
          const chargeStep = this._state('number', 'charge_price_threshold')?.attributes?.step ?? 0.01;
          const chargeScale = { scaleMin, scaleMax, scaleRange, padT, plotH, padL, padR, chartW, step: chargeStep };
          return svg`
          <g class="threshold-line-group" data-type="charge"
            @pointerdown=${(e) => this._onThresholdPointerDown(e, 'charge', chargeScale)}>
            <line x1="${padL}" y1="${yPos(chargeThreshold)}" x2="${chartW - padR}" y2="${yPos(chargeThreshold)}"
              stroke="transparent" stroke-width="22" class="threshold-hit-area" />
            <line x1="${padL}" y1="${yPos(chargeThreshold)}" x2="${chartW - padR}" y2="${yPos(chargeThreshold)}"
              stroke="var(--vcc-success, #4caf50)" stroke-width="1.5" stroke-dasharray="6,4" class="threshold-visible-line" />
            <text x="${chartW - padR + 4}" y="${yPos(chargeThreshold) + 3.5}" text-anchor="start"
              class="plan-threshold-label" fill="var(--vcc-success, #4caf50)">${Math.round(chargeThreshold * 10) / 10}</text>
          </g>`;
        })() : nothing}

        <!-- Discharge threshold line (interactive) -->
        ${dischargeThreshold !== null && dischargeThreshold >= scaleMin && dischargeThreshold <= scaleMax ? (() => {
          const dischargeStep = this._state('number', 'discharge_price_threshold')?.attributes?.step ?? 0.01;
          const dischargeScale = { scaleMin, scaleMax, scaleRange, padT, plotH, padL, padR, chartW, step: dischargeStep };
          return svg`
          <g class="threshold-line-group" data-type="discharge"
            @pointerdown=${(e) => this._onThresholdPointerDown(e, 'discharge', dischargeScale)}>
            <line x1="${padL}" y1="${yPos(dischargeThreshold)}" x2="${chartW - padR}" y2="${yPos(dischargeThreshold)}"
              stroke="transparent" stroke-width="22" class="threshold-hit-area" />
            <line x1="${padL}" y1="${yPos(dischargeThreshold)}" x2="${chartW - padR}" y2="${yPos(dischargeThreshold)}"
              stroke="#ff6600" stroke-width="1.5" stroke-dasharray="6,4" class="threshold-visible-line" />
            <text x="${chartW - padR + 4}" y="${yPos(dischargeThreshold) + 3.5}" text-anchor="start"
              class="plan-threshold-label" fill="var(--vcc-warning, #ff6600)">${Math.round(dischargeThreshold * 10) / 10}</text>
          </g>`;
        })() : nothing}

        <!-- Y-axis unit -->
        <text x="${padL + 12}" y="${padT - 14}" text-anchor="end"
          class="plan-axis-unit">ct/kWh</text>

        <!-- X-axis labels (every 2 hours) -->
        ${enrichedPlan.map((entry, i) => {
          const h = entry.hour ?? i;
          if (h % 2 !== 0 && !(showCurrentHour && h === currentHour)) return nothing;
          const x = padL + i * barW + barW / 2;
          return svg`
            <text x="${x}" y="${chartH - 6}" text-anchor="middle"
              class="plan-axis-label ${showCurrentHour && h === currentHour ? 'plan-current-hour' : ''}"
            >${String(h).padStart(2, '0')}</text>
          `;
        })}

        <!-- Bar tooltip -->
        ${(() => {
          if (!this._tooltipBar || this._tooltipBar.chartId !== chartId) return nothing;
          const { index } = this._tooltipBar;
          if (index < 0 || index >= enrichedPlan.length) return nothing;
          const entry = enrichedPlan[index];
          const price = Number(entry.price);
          if (!Number.isFinite(price)) return nothing;
          const h = entry.hour ?? index;
          const barCenterX = padL + index * barW + barW / 2;
          const barTopY = yPos(price);
          const barBaseY = zeroInRange ? yPos(0) : padT + plotH;
          const barTop = Math.min(barTopY, barBaseY);
          const tw = 96;
          const th = 38;
          let ty = barTop - th - 8;
          if (ty < 2) ty = Math.max(barTopY, barBaseY) + 8;
          let tx = barCenterX - tw / 2;
          tx = Math.max(padL, Math.min(tx, chartW - padR - tw));
          const timeLabel = `${String(h).padStart(2, '0')}:00`;
          const priceLabel = `${price.toFixed(2)} ct/kWh`;
          return svg`
            <g class="plan-bar-tooltip">
              <rect x="${tx}" y="${ty}" width="${tw}" height="${th}" rx="5"
                fill="var(--vcc-card-bg, var(--card-background-color, #fff))"
                fill-opacity="0.95"
                stroke="var(--vcc-border, #e0e0e0)" stroke-width="0.8" />
              <text x="${tx + tw / 2}" y="${ty + 15}" text-anchor="middle"
                class="plan-tooltip-time">${timeLabel}</text>
              <text x="${tx + tw / 2}" y="${ty + 30}" text-anchor="middle"
                class="plan-tooltip-price">${priceLabel}</text>
            </g>
          `;
        })()}

        <!-- Manual action picker -->
        ${(() => {
          if (!this._pickerBar || this._pickerBar.chartId !== chartId) return nothing;
          const { index } = this._pickerBar;
          if (index < 0 || index >= enrichedPlan.length) return nothing;
          const entry = enrichedPlan[index];
          const price = Number(entry.price);
          if (!Number.isFinite(price)) return nothing;
          const h = entry.hour ?? index;
          const entryDate = entry.date;
          const barCenterX = padL + index * barW + barW / 2;
          const barTopY = yPos(price);
          const barBaseY = zeroInRange ? yPos(0) : padT + plotH;
          const barTop = Math.min(barTopY, barBaseY);
          const currentAction = entry.displayAction || entry.action || 'idle';
          const timeLabel = `${String(h).padStart(2, '0')}:00`;
          const priceLabel = `${price.toFixed(2)} ct/kWh`;
          const buttons = [
            { key: 'charge',    label: 'Charge',  color: 'var(--vcc-success, #4caf50)' },
            { key: 'pv_charge', label: 'PV',      color: 'var(--vcc-pv-charge, #ffb74d)' },
            { key: 'discharge', label: 'Disch.',  color: '#ff6600' },
            { key: 'idle',      label: 'Idle',    color: 'var(--vcc-disabled, #9e9e9e)' },
          ];
          const btnW = 40;
          const btnH = 24;
          const gap = 4;
          const totalBtnW = btnW * buttons.length + gap * (buttons.length - 1);
          const pw = Math.max(168, totalBtnW + 16);
          const ph = 70;
          let px;
          let py;
          if (this._pickerBar.anchorX != null && this._pickerBar.anchorY != null && this._pickerBar.svgEl) {
            const anchor = this._clientToSvgPoint(this._pickerBar.anchorX, this._pickerBar.anchorY, this._pickerBar.svgEl);
            px = anchor.x - pw / 2;
            py = anchor.y - ph / 2;
          } else {
            py = barTop - ph - 8;
            if (py < 2) py = Math.max(barTopY, barBaseY) + 8;
            px = barCenterX - pw / 2;
          }
          px = Math.max(padL, Math.min(px, chartW - padR - pw));
          py = Math.max(2, Math.min(py, chartH - ph - 2));
          const btnY = py + 30;
          const btnStartX = px + (pw - totalBtnW) / 2;
          return svg`
            <g class="plan-picker"
              @contextmenu=${(e) => { e.preventDefault(); e.stopPropagation(); }}
              @pointerdown=${(e) => e.stopPropagation()}>
              <rect x="${px}" y="${py}" width="${pw}" height="${ph}" rx="6"
                class="plan-picker-bg"
                fill="var(--vcc-card-bg, var(--card-background-color, #fff))"
                fill-opacity="0.97"
                stroke="var(--vcc-border, #e0e0e0)" stroke-width="0.8" />
              <text x="${px + pw / 2}" y="${py + 16}" text-anchor="middle"
                class="plan-picker-title">${timeLabel} · ${priceLabel}</text>
              ${buttons.map((b, bi) => {
                const bx = btnStartX + bi * (btnW + gap);
                const isActive = currentAction === b.key;
                return svg`
                  <g class="plan-picker-btn"
                    data-action=${b.key}
                    @click=${(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      this._setPlanHourAction(h, b.key, entryDate);
                      this._closePicker();
                    }}>
                    <rect x="${bx}" y="${btnY}" width="${btnW}" height="${btnH}" rx="4"
                      fill=${isActive ? b.color : 'transparent'}
                      stroke=${b.color} stroke-width="1.5"
                      pointer-events="all" />
                    <text x="${bx + btnW / 2}" y="${btnY + 16}" text-anchor="middle"
                      class="plan-picker-label ${isActive ? 'plan-picker-label-active' : ''}">${b.label}</text>
                  </g>
                `;
              })}
            </g>
          `;
        })()}
      </svg>
    `;
  }

  _onBarClick(e, chartId, index) {
    if (this._barLongPressFired) {
      this._barLongPressFired = false;
      e.preventDefault();
      e.stopPropagation();
      return;
    }
    if (this._tooltipBar?.chartId === chartId && this._tooltipBar?.index === index) {
      this._tooltipBar = null;
      if (this._tooltipHideTimer) {
        clearTimeout(this._tooltipHideTimer);
        this._tooltipHideTimer = null;
      }
      this.requestUpdate();
      return;
    }
    this._tooltipBar = { chartId, index };
    if (this._pickerBar) this._closePicker();
    if (this._tooltipHideTimer) clearTimeout(this._tooltipHideTimer);
    this._tooltipHideTimer = setTimeout(() => {
      this._tooltipBar = null;
      this._tooltipHideTimer = null;
      this.requestUpdate();
    }, 10000);
    this.requestUpdate();
  }

  _onBarContextMenu(e, chartId, index) {
    e.preventDefault();
    e.stopPropagation();
    const group = e.currentTarget;
    if (group?.dataset?.past === 'true') return;
    const svgEl = group?.closest('svg') || null;
    this._openPicker(chartId, index, e.clientX, e.clientY, svgEl);
  }

  _onBarPointerDown(e, chartId, index) {
    if (e.button !== undefined && e.button !== 0) return;
    const group = e.currentTarget;
    if (group?.dataset?.past === 'true') return;
    this._barLongPressFired = false;
    if (this._barHoldTimer) clearTimeout(this._barHoldTimer);
    this._barHoldStart = { x: e.clientX, y: e.clientY };
    const svgEl = group?.closest('svg') || null;
    this._barHoldTimer = setTimeout(() => {
      this._barHoldTimer = null;
      this._barLongPressFired = true;
      const start = this._barHoldStart || { x: e.clientX, y: e.clientY };
      this._openPicker(chartId, index, start.x, start.y, svgEl);
    }, 500);
  }

  _onBarPointerUp(e) {
    if (this._barHoldTimer) {
      clearTimeout(this._barHoldTimer);
      this._barHoldTimer = null;
    }
    this._barHoldStart = null;
  }

  _onBarPointerMove(e) {
    if (!this._barHoldStart || !this._barHoldTimer) return;
    const dx = e.clientX - this._barHoldStart.x;
    const dy = e.clientY - this._barHoldStart.y;
    if (dx * dx + dy * dy > 36) {
      clearTimeout(this._barHoldTimer);
      this._barHoldTimer = null;
      this._barHoldStart = null;
    }
  }

  _onBarPointerMove(e) {
    if (!this._barHoldStart || !this._barHoldTimer) return;
    const dx = e.clientX - this._barHoldStart.x;
    const dy = e.clientY - this._barHoldStart.y;
    if (dx * dx + dy * dy > 36) {
      clearTimeout(this._barHoldTimer);
      this._barHoldTimer = null;
      this._barHoldStart = null;
    }
  }

  _openPicker(chartId, index, anchorX = null, anchorY = null, svgEl = null) {
    this._pickerBar = { chartId, index, anchorX, anchorY, svgEl };
    if (this._tooltipBar) {
      this._tooltipBar = null;
      if (this._tooltipHideTimer) {
        clearTimeout(this._tooltipHideTimer);
        this._tooltipHideTimer = null;
      }
    }
    if (this._pickerHideTimer) clearTimeout(this._pickerHideTimer);
    this._pickerHideTimer = setTimeout(() => {
      this._pickerBar = null;
      this._pickerHideTimer = null;
      this.requestUpdate();
    }, 15000);
    document.addEventListener('pointerdown', this._onDocumentPointerDownBound, true);
    this.requestUpdate();
  }

  _closePicker() {
    this._pickerBar = null;
    if (this._pickerHideTimer) {
      clearTimeout(this._pickerHideTimer);
      this._pickerHideTimer = null;
    }
    document.removeEventListener('pointerdown', this._onDocumentPointerDownBound, true);
    this.requestUpdate();
  }

  _onDocumentPointerDown(e) {
    if (!this._pickerBar) {
      document.removeEventListener('pointerdown', this._onDocumentPointerDownBound, true);
      return;
    }
    const path = e.composedPath ? e.composedPath() : (e.path || []);
    // Picker itself: keep open, let click handlers inside run
    if (path.some(n => n && n.classList && n.classList.contains('plan-picker'))) {
      return;
    }
    // Click on a different bar: close current picker; the bar handler will open a new one
    this._closePicker();
  }

  // ── Cost statistics view ─────────────────────────────────

  _startOfDay(date) {
    const d = new Date(date);
    d.setHours(0, 0, 0, 0);
    return d;
  }

  _addPeriod(date, period, amount) {
    const d = new Date(date);
    if (period === 'hour') d.setHours(d.getHours() + amount);
    else if (period === 'day') d.setDate(d.getDate() + amount);
    else if (period === 'month') d.setMonth(d.getMonth() + amount);
    return d;
  }

  _addCostRangePeriods(date, range, amount) {
    const d = new Date(date);
    if (range === 'week') d.setDate(d.getDate() + amount * 7);
    else if (range === 'month') d.setMonth(d.getMonth() + amount);
    else if (range === 'year') d.setFullYear(d.getFullYear() + amount);
    else d.setDate(d.getDate() + amount);
    return d;
  }

  _getCurrentCostPeriodStart(range, now = new Date()) {
    if (range === 'week') {
      const start = this._startOfDay(now);
      const mondayOffset = (start.getDay() + 6) % 7;
      start.setDate(start.getDate() - mondayOffset);
      return start;
    }
    if (range === 'month') return new Date(now.getFullYear(), now.getMonth(), 1);
    if (range === 'year') return new Date(now.getFullYear(), 0, 1);
    return this._startOfDay(now);
  }

  _getCostRangeWindow(range) {
    const now = new Date();
    const offset = this._costRangeOffsets?.[range] ?? 0;
    const currentStart = this._getCurrentCostPeriodStart(range, now);
    const start = this._addCostRangePeriods(currentStart, range, offset);
    const periodEnd = this._addCostRangePeriods(start, range, 1);
    return {
      start,
      end: offset === 0 ? now : periodEnd,
      queryStart: this._addPeriod(start, COST_RANGES[range].period, -1),
      period: COST_RANGES[range].period,
      range,
      offset,
    };
  }

  _costRefreshBucket(range) {
    const now = new Date();
    const offset = this._costRangeOffsets?.[range] ?? 0;
    if (offset < 0) return 'archive';
    if (range === 'year') return `${now.getFullYear()}-${now.getMonth()}`;
    if (range === 'month' || range === 'week') return now.toISOString().slice(0, 10);
    return `${now.toISOString().slice(0, 13)}:${Math.floor(now.getMinutes() / 5)}`;
  }

  _costStatsKey(range) {
    const isEnergy = this._costMode === 'energy';
    const ids = isEnergy
      ? [this._eid('sensor', 'grid_energy_import'), this._eid('sensor', 'grid_energy_export')]
      : [this._eid('sensor', 'grid_energy_cost'), this._eid('sensor', 'grid_energy_revenue')];
    const window = this._getCostRangeWindow(range);
    const endKey = window.offset === 0 ? 'current' : window.end.getTime();
    return `${this._costMode}|${range}|${window.period}|${window.offset}|${window.start.getTime()}|${endKey}|${this._costRefreshBucket(range)}|${ids.join(',')}`;
  }

  _setCostRange(range) {
    if (!COST_RANGES[range]) return;
    if (this._costRange === range) {
      const currentOffset = this._costRangeOffsets?.[range] ?? 0;
      if (currentOffset === 0) return;
      this._costRangeOffsets = { ...this._costRangeOffsets, [range]: 0 };
      this._costStatsState = { status: 'idle', key: null, points: [], error: null };
      this.requestUpdate();
      return;
    }
    this._costRange = range;
    this._costRangeOffsets = { ...this._costRangeOffsets, [range]: 0 };
    this._costStatsState = { status: 'idle', key: null, points: [], error: null };
    this.requestUpdate();
  }

  _setCostMode(mode) {
    if (this._costMode === mode) return;
    this._costMode = mode;
    this._costStatsState = { status: 'idle', key: null, points: [], error: null };
    this.requestUpdate();
  }

  _shiftCostPeriod(amount) {
    const range = COST_RANGES[this._costRange] ? this._costRange : 'day';
    const currentOffset = this._costRangeOffsets?.[range] ?? 0;
    const nextOffset = Math.min(0, currentOffset + amount);
    if (nextOffset === currentOffset) return;
    this._costRangeOffsets = { ...this._costRangeOffsets, [range]: nextOffset };
    this._costStatsState = { status: 'idle', key: null, points: [], error: null };
    this.requestUpdate();
  }

  _formatCostPeriodLabel(range) {
    const window = this._getCostRangeWindow(range);
    const date = window.start;
    if (range === 'year') return date.toLocaleDateString(undefined, { year: 'numeric' });
    if (range === 'month') return date.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
    if (range === 'week') {
      const end = this._addPeriod(window.start, 'day', 6);
      return `${this._formatCostDayMonth(window.start)} - ${this._formatCostDayMonth(end)}, ${end.getFullYear()}`;
    }
    return `${date.toLocaleDateString(undefined, { weekday: 'short' })}, ${this._formatCostDayMonth(date)} ${date.getFullYear()}`;
  }

  _formatCostDayMonth(date) {
    const month = date.toLocaleDateString(undefined, { month: 'long' });
    return `${date.getDate()}. ${month}`;
  }

  _refreshCostStats() {
    this._costStatsState = { status: 'idle', key: null, points: [], error: null };
    this.requestUpdate();
  }

  _ensureCostStatsLoaded() {
    const range = COST_RANGES[this._costRange] ? this._costRange : 'day';
    const key = this._costStatsKey(range);
    if (this._costStatsState.key === key && this._costStatsState.status !== 'idle') return;

    const window = this._getCostRangeWindow(range);
    const isEnergy = this._costMode === 'energy';
    const entityId1 = isEnergy ? this._eid('sensor', 'grid_energy_import') : this._eid('sensor', 'grid_energy_cost');
    const entityId2 = isEnergy ? this._eid('sensor', 'grid_energy_export') : this._eid('sensor', 'grid_energy_revenue');

    this._costStatsState = { status: 'loading', key, points: [], error: null };
    this.requestUpdate();

    const statsMessage = {
      type: 'recorder/statistics_during_period',
      statistic_ids: [entityId1, entityId2],
      start_time: window.queryStart.toISOString(),
      end_time: window.end.toISOString(),
      period: window.period,
    };

    this._callWS({
      ...statsMessage,
      types: ['change', 'sum'],
    })
      .catch(() => this._callWS({
        ...statsMessage,
        types: ['sum'],
      }))
      .then((result) => {
        if (this._costRange !== range || this._costStatsState.key !== key) return;
        const points = this._buildCostPoints(result || {}, entityId1, entityId2, window);
        this._costStatsState = {
          status: points.length > 0 ? 'ready' : 'empty',
          key,
          points,
          error: null,
        };
        this.requestUpdate();
      })
      .catch((err) => {
        if (this._costStatsState.key !== key) return;
        this._costStatsState = {
          status: 'error',
          key,
          points: [],
          error: err?.message || 'Unable to load cost statistics',
        };
        this.requestUpdate();
      });
  }

  _statTimeMs(row) {
    const raw = row?.start;
    if (typeof raw === 'number') return raw;
    const parsed = Date.parse(raw);
    return Number.isFinite(parsed) ? parsed : null;
  }

  _numberOrNull(value) {
    const num = Number(value);
    return Number.isFinite(num) ? num : null;
  }

  _buildDeltaMap(rows = [], window) {
    const map = new Map();
    let previousSum = null;
    const sorted = [...rows]
      .map(row => ({ row, startMs: this._statTimeMs(row) }))
      .filter(item => item.startMs !== null)
      .sort((a, b) => a.startMs - b.startMs);

    for (const { row, startMs } of sorted) {
      const sum = this._numberOrNull(row.sum);
      let delta = this._numberOrNull(row.change);
      if (delta === null && sum !== null && previousSum !== null) {
        delta = Math.max(0, sum - previousSum);
      }
      if (sum !== null) previousSum = sum;
      if (startMs < window.start.getTime() || startMs >= window.end.getTime()) continue;
      if (delta !== null) map.set(startMs, Math.max(0, delta));
    }
    return map;
  }

  _buildCostPoints(result, costId, revenueId, window) {
    const costMap = this._buildDeltaMap(result[costId] || [], window);
    const revenueMap = this._buildDeltaMap(result[revenueId] || [], window);
    const starts = [...new Set([...costMap.keys(), ...revenueMap.keys()])].sort((a, b) => a - b);
    return starts.map(startMs => {
      const cost = costMap.get(startMs) ?? 0;
      const revenue = revenueMap.get(startMs) ?? 0;
      return {
        startMs,
        label: this._formatCostBucketLabel(startMs, window.period, window.range),
        cost,
        revenue,
        net: revenue - cost,
      };
    });
  }

  _formatCostBucketLabel(startMs, period, range) {
    const d = new Date(startMs);
    if (period === 'hour') return String(d.getHours()).padStart(2, '0');
    if (period === 'month') return d.toLocaleDateString(undefined, { month: 'short' });
    if (range === 'month') return String(d.getDate());
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }

  _formatMoney(value, digits = 2) {
    const amount = Number(value) || 0;
    return `${amount.toFixed(digits)} EUR`;
  }

  _formatSignedMoney(value) {
    const amount = Number(value) || 0;
    const sign = amount > 0 ? '+' : '';
    return `${sign}${amount.toFixed(2)} EUR`;
  }

  _formatEnergy(value, digits = 2) {
    const amount = Number(value) || 0;
    return `${amount.toFixed(digits)} kWh`;
  }

  _formatSignedEnergy(value) {
    const amount = Number(value) || 0;
    const sign = amount > 0 ? '+' : '';
    return `${sign}${amount.toFixed(2)} kWh`;
  }

  _renderCostChart(points) {
    if (!points.length) return null;

    const isEnergy = this._costMode === 'energy';
    const unitLabel = isEnergy ? 'kWh' : 'EUR';
    const costLabel = isEnergy ? 'import' : 'cost';
    const revenueLabel = isEnergy ? 'export' : 'revenue';

    const chartW = 640;
    const chartH = 320;
    const padL = 54;
    const padR = 24;
    const padT = 36;
    const padB = 42;
    const plotW = chartW - padL - padR;
    const plotH = chartH - padT - padB;
    const maxValue = Math.max(0.01, ...points.flatMap(p => [p.cost, p.revenue]));
    const scaleMax = maxValue * 1.15;
    const groupW = plotW / points.length;
    const barGap = Math.min(4, Math.max(1.5, groupW * 0.08));
    const barW = Math.max(1.5, Math.min(18, (groupW - barGap * 3) / 2));
    const yPos = (value) => padT + plotH - (value / scaleMax) * plotH;

    const tickCount = 4;
    const yTicks = Array.from({ length: tickCount + 1 }, (_, i) => {
      const val = (scaleMax * i) / tickCount;
      return { val, y: yPos(val) };
    });

    const range = COST_RANGES[this._costRange] ? this._costRange : 'day';
    const labelEvery = range === 'day' ? 2 : Math.max(1, Math.ceil(points.length / 8));

    return svg`
      <svg class="cost-chart" viewBox="0 0 ${chartW} ${chartH}" preserveAspectRatio="xMidYMid meet">
        ${yTicks.map(t => svg`
          <line x1="${padL}" y1="${t.y}" x2="${chartW - padR}" y2="${t.y}"
            stroke="var(--vcc-border, #e0e0e0)" stroke-width="0.5"
            stroke-dasharray="${t.val === 0 ? 'none' : '4,3'}" />
          <text x="${padL - 7}" y="${t.y + 3.5}" text-anchor="end"
            class="cost-axis-label">${isEnergy ? this._formatEnergy(t.val, t.val >= 10 ? 0 : 1).replace(' kWh', '') : this._formatMoney(t.val, t.val >= 10 ? 0 : 1).replace(' EUR', '')}</text>
        `)}

        ${points.map((point, i) => {
          const xCenter = padL + i * groupW + groupW / 2;
          const costH = padT + plotH - yPos(point.cost);
          const revenueH = padT + plotH - yPos(point.revenue);
          return svg`
            <g class="cost-bar-group" @click=${(e) => this._onBarClick(e, 'history', i)}>
              <rect x="${xCenter - barW - barGap / 2}" y="${yPos(point.cost)}"
                width="${barW}" height="${Math.max(1, costH)}"
                fill="var(--vcc-error, #f44336)" opacity="0.72" rx="1.5" />
              <rect x="${xCenter + barGap / 2}" y="${yPos(point.revenue)}"
                width="${barW}" height="${Math.max(1, revenueH)}"
                fill="var(--vcc-success, #4caf50)" opacity="0.78" rx="1.5" />
            </g>
            ${((range === 'day' && new Date(point.startMs).getHours() % labelEvery === 0)
              || (range !== 'day' && (i % labelEvery === 0 || i === points.length - 1))) ? svg`
              <text x="${xCenter}" y="${chartH - 10}" text-anchor="middle"
                class="cost-axis-label">${point.label}</text>
            ` : nothing}
          `;
        })}

        <text x="${padL + 0}" y="${padT - 14}" text-anchor="end"
          class="cost-axis-unit">${unitLabel}</text>

        ${(() => {
          if (!this._tooltipBar || this._tooltipBar.chartId !== 'history') return nothing;
          const { index } = this._tooltipBar;
          if (index < 0 || index >= points.length) return nothing;
          const point = points[index];
          const xCenter = padL + index * groupW + groupW / 2;
          const barTopY = Math.min(yPos(point.cost), yPos(point.revenue));
          const tw = 120;
          const th = 52;
          let ty = barTopY - th - 8;
          if (ty < 2) ty = Math.max(yPos(point.cost), yPos(point.revenue)) + Math.max(padT + plotH - yPos(point.cost), padT + plotH - yPos(point.revenue)) + 8;
          let tx = xCenter - tw / 2;
          tx = Math.max(padL, Math.min(tx, chartW - padR - tw));
          const costVal = isEnergy ? this._formatEnergy(point.cost) : this._formatMoney(point.cost);
          const revVal = isEnergy ? this._formatEnergy(point.revenue) : this._formatMoney(point.revenue);
          const timeLabel = COST_RANGES[range]?.period === 'hour' ? `${point.label}:00` : point.label;
          return svg`
            <g class="cost-bar-tooltip">
              <rect x="${tx}" y="${ty}" width="${tw}" height="${th}" rx="5"
                fill="var(--vcc-card-bg, var(--card-background-color, #fff))"
                fill-opacity="0.95"
                stroke="var(--vcc-border, #e0e0e0)" stroke-width="0.8" />
              <text x="${tx + tw / 2}" y="${ty + 15}" text-anchor="middle"
                class="cost-tooltip-time">${timeLabel}</text>
              <text x="${tx + tw / 2}" y="${ty + 31}" text-anchor="middle"
                class="cost-tooltip-cost">${costLabel}: ${costVal}</text>
              <text x="${tx + tw / 2}" y="${ty + 47}" text-anchor="middle"
                class="cost-tooltip-revenue">${revenueLabel}: ${revVal}</text>
            </g>
          `;
        })()}
      </svg>
    `;
  }

  _renderCostSummary(points) {
    const totalCost = points.reduce((sum, p) => sum + p.cost, 0);
    const totalRevenue = points.reduce((sum, p) => sum + p.revenue, 0);
    const net = totalRevenue - totalCost;
    const isEnergy = this._costMode === 'energy';
    const costLabel = isEnergy ? 'Import' : 'Cost';
    const revenueLabel = isEnergy ? 'Export' : 'Revenue';
    const netLabel = 'Net';
    return html`
      <div class="cost-summary">
        <div class="cost-summary-item cost">
          <span>${costLabel}</span>
          <strong>${isEnergy ? this._formatEnergy(totalCost) : this._formatMoney(totalCost)}</strong>
        </div>
        <div class="cost-summary-item revenue">
          <span>${revenueLabel}</span>
          <strong>${isEnergy ? this._formatEnergy(totalRevenue) : this._formatMoney(totalRevenue)}</strong>
        </div>
        <div class="cost-summary-item ${net >= 0 ? 'positive' : 'negative'}">
          <span>${netLabel}</span>
          <strong>${isEnergy ? this._formatSignedEnergy(net) : this._formatSignedMoney(net)}</strong>
        </div>
      </div>
    `;
  }

  _renderHistoryView() {
    const isEnergy = this._costMode === 'energy';
    const costEntity1 = isEnergy ? this._state('sensor', 'grid_energy_import') : this._state('sensor', 'grid_energy_cost');
    const costEntity2 = isEnergy ? this._state('sensor', 'grid_energy_export') : this._state('sensor', 'grid_energy_revenue');
    if (!costEntity1 || !costEntity2) {
      const msg = isEnergy
        ? 'Grid energy import and export sensors are not available for this entity prefix.'
        : 'Grid energy cost and revenue sensors are not available for this entity prefix.';
      return html`
        <div class="warning">
          <ha-icon icon="mdi:alert-outline"></ha-icon>
          <span>${msg}</span>
        </div>`;
    }

    const range = COST_RANGES[this._costRange] ? this._costRange : 'day';
    this._ensureCostStatsLoaded();

    const state = this._costStatsState;
    const points = state.points || [];
    const costOffset = this._costRangeOffsets?.[range] ?? 0;
    const periodLabel = this._formatCostPeriodLabel(range);

    const costLegendLabel = isEnergy ? 'Import' : 'Cost';
    const revenueLegendLabel = isEnergy ? 'Export' : 'Revenue';

    return html`
      <div class="history-container">
        <div class="history-toolbar">
          <div class="cost-mode-group">
            <button
              class="cost-mode-btn ${!isEnergy ? 'active' : ''}"
              @click=${() => this._setCostMode('cost')}
              title="Cost / Revenue in EUR"
            >
              <ha-icon icon="mdi:currency-eur"></ha-icon>
              <span>EUR</span>
            </button>
            <button
              class="cost-mode-btn ${isEnergy ? 'active' : ''}"
              @click=${() => this._setCostMode('energy')}
              title="Import / Export in kWh"
            >
              <ha-icon icon="mdi:transmission-tower"></ha-icon>
              <span>kWh</span>
            </button>
          </div>
          <div class="cost-range-group">
            ${Object.entries(COST_RANGES).map(([key, meta]) => html`
              <button
                class="cost-range-btn ${range === key ? 'active' : ''}"
                @click=${() => this._setCostRange(key)}
                title=${meta.label}
              >
                <ha-icon .icon=${meta.icon}></ha-icon>
                <span>${meta.label}</span>
              </button>
            `)}
          </div>
          <div class="cost-period-nav">
            <button
              class="cost-period-btn"
              @click=${() => this._shiftCostPeriod(-1)}
              title="Previous ${COST_RANGES[range].label.toLowerCase()}"
            >
              <ha-icon icon="mdi:chevron-left"></ha-icon>
            </button>
            <div class="cost-period-label">${periodLabel}</div>
            <button
              class="cost-period-btn"
              ?disabled=${costOffset === 0}
              @click=${() => this._shiftCostPeriod(1)}
              title="Next ${COST_RANGES[range].label.toLowerCase()}"
            >
              <ha-icon icon="mdi:chevron-right"></ha-icon>
            </button>
            <button class="cost-refresh-btn"
              @click=${() => this._refreshCostStats()}
              title="Refresh statistics">
              <ha-icon icon="mdi:refresh"></ha-icon>
            </button>
          </div>
        </div>

        ${state.status === 'loading' ? html`
          <div class="cost-loading">
            <ha-icon icon="mdi:chart-bar"></ha-icon>
            <span>Loading statistics...</span>
          </div>
        ` : nothing}

        ${state.status === 'error' ? html`
          <div class="warning">
            <ha-icon icon="mdi:alert-outline"></ha-icon>
            <span>${state.error || 'Unable to load cost statistics.'}</span>
          </div>
        ` : nothing}

        ${state.status === 'empty' ? html`
          <div class="warning">
            <ha-icon icon="mdi:alert-outline"></ha-icon>
            <span>No ${isEnergy ? 'energy' : 'cost'} statistics are available for this range. Check that recorder includes these sensors and has enough statistics data.</span>
          </div>
        ` : nothing}

        ${state.status === 'ready' ? html`
          ${this._renderCostSummary(points)}
          ${this._renderCostChart(points)}
          <div class="plan-legend">
            <div class="plan-legend-item">
              <span class="plan-legend-dot" style="background: var(--vcc-error)"></span>
              <span>${costLegendLabel}</span>
            </div>
            <div class="plan-legend-item">
              <span class="plan-legend-dot" style="background: var(--vcc-success)"></span>
              <span>${revenueLegendLabel}</span>
            </div>
          </div>
        ` : nothing}
      </div>`;
  }

  // ── Plan view ────────────────────────────────────────────

  _renderPlanView() {
    const planEntity = this._state('sensor', 'charge_plan');
    const plan = planEntity?.attributes?.plan;

    if (!plan || !Array.isArray(plan) || plan.length === 0) {
      return html`
        <div class="warning">
          <ha-icon icon="mdi:alert-outline"></ha-icon>
          <span>No charge plan data available.</span>
        </div>`;
    }

    const priceEntity = this._state('sensor', 'current_price');
    const currentPrice = priceEntity?.state;
    const attrs = priceEntity?.attributes || {};

    // --- Split plan by date ---
    const dates = [...new Set(plan.map(p => p.date))].sort();
    const todayDate = dates[0];
    const tomorrowDate = dates.length > 1 ? dates[1] : null;

    let todayPlan = plan.filter(p => p.date === todayDate);
    const rawTomorrowPlan = tomorrowDate ? plan.filter(p => p.date === tomorrowDate) : [];

    // Fallback: enrich today's plan with EPEX prices if entries lack them
    const todayHasPrices = todayPlan.some(p => p.price !== undefined && p.price !== null);
    if (!todayHasPrices) {
      const priceMap = this._extractEpexPrices(attrs);
      if (Object.keys(priceMap).length > 0) {
        todayPlan = todayPlan.map(p => ({
          ...p,
          price: priceMap[p.hour] ?? null,
        }));
      }
    }

    // Fallback: enrich tomorrow's plan with EPEX prices if entries lack them
    let tomorrowPlan = rawTomorrowPlan;
    const tomorrowHasPrices = tomorrowPlan.some(p => p.price !== undefined && p.price !== null);
    if (!tomorrowHasPrices && tomorrowDate) {
      const tomorrow = new Date();
      tomorrow.setDate(tomorrow.getDate() + 1);
      const tomorrowPriceMap = this._extractEpexPrices(attrs, tomorrow);
      if (Object.keys(tomorrowPriceMap).length > 0) {
        tomorrowPlan = tomorrowPlan.map(p => ({
          ...p,
          price: tomorrowPriceMap[p.hour] ?? null,
        }));
      }
    }

    todayPlan = this._enrichPlanDisplayState(todayPlan);
    tomorrowPlan = this._enrichPlanDisplayState(tomorrowPlan);

    const chargeThreshold = parseFloat(this._val('number', 'charge_price_threshold'));
    const dischargeThreshold = parseFloat(this._val('number', 'discharge_price_threshold'));
    // Use pending overrides until HA entity catches up
    const ctCharge = this._pendingThresholds.charge ?? (isNaN(chargeThreshold) ? null : chargeThreshold);
    const ctDischarge = this._pendingThresholds.discharge ?? (isNaN(dischargeThreshold) ? null : dischargeThreshold);
    // Clear pending values once entity state matches
    if (this._pendingThresholds.charge !== undefined && !isNaN(chargeThreshold) && Math.abs(chargeThreshold - this._pendingThresholds.charge) < 0.001) {
      delete this._pendingThresholds.charge;
    }
    if (this._pendingThresholds.discharge !== undefined && !isNaN(dischargeThreshold) && Math.abs(dischargeThreshold - this._pendingThresholds.discharge) < 0.001) {
      delete this._pendingThresholds.discharge;
    }

    const currentHour = new Date().getHours();

    // Compute shared y-axis scale across both plans
    const allValidPrices = [...todayPlan, ...tomorrowPlan]
      .map(p => p.price)
      .filter(p => p !== null && p !== undefined)
      .map(Number)
      .filter(Number.isFinite);
    let sharedScaleMin = null;
    let sharedScaleMax = null;
    if (allValidPrices.length > 0) {
      const minP = Math.min(...allValidPrices);
      const maxP = Math.max(...allValidPrices);
      const pRange = maxP - minP || 1;
      sharedScaleMin = Math.min(-1, minP);
      sharedScaleMax = Math.max(1, Math.ceil(maxP + pRange * 0.1));
    }

    const todayChart = this._renderPriceChart(todayPlan, { showCurrentHour: true, chargeThreshold: ctCharge, dischargeThreshold: ctDischarge, forcedScaleMin: sharedScaleMin, forcedScaleMax: sharedScaleMax, chartId: 'today' });

    // Tomorrow chart: render if we have plan entries (even without prices, shows actions)
    const tomorrowHasAnyPrices = tomorrowPlan.some(p => p.price !== undefined && p.price !== null);
    const tomorrowChart = tomorrowHasAnyPrices
      ? this._renderPriceChart(tomorrowPlan, { chargeThreshold: ctCharge, dischargeThreshold: ctDischarge, forcedScaleMin: sharedScaleMin, forcedScaleMax: sharedScaleMax, chartId: 'tomorrow' })
      : null;

    if (!todayChart && !tomorrowChart) {
      return html`
        <div class="warning">
          <ha-icon icon="mdi:alert-outline"></ha-icon>
          <span>No EPEX price data available.</span>
        </div>`;
    }

    return html`
      <div class="plan-chart-container">
        <div class="plan-toolbar">
          <div class="plan-toolbar-left">
            ${currentPrice != null && currentPrice !== 'unavailable' && currentPrice !== 'unknown' ? html`
              <div class="plan-current-price">
                <ha-icon icon="mdi:currency-eur"></ha-icon>
                <span><strong>${(parseFloat(currentPrice) * 100).toFixed(2)} ct/kWh</strong></span>
              </div>
            ` : nothing}
          </div>
          <div class="plan-toolbar-right">
            ${(() => {
              const lastUpdate = this._state('sensor', 'last_schedule_update');
              if (!lastUpdate || lastUpdate.state === 'unknown' || lastUpdate.state === 'unavailable') return nothing;
              const dt = new Date(lastUpdate.state);
              if (isNaN(dt.getTime())) return nothing;
              const diffMs = Date.now() - dt.getTime();
              const diffMin = Math.floor(diffMs / 60000);
              let ago;
              if (diffMin < 1) ago = 'just now';
              else if (diffMin < 60) ago = `${diffMin} min ago`;
              else { const h = Math.floor(diffMin / 60); ago = `${h}h ${diffMin % 60}m ago`; }
              return html`<span class="plan-last-update">Updated: ${ago}</span>`;
            })()}
            <button class="action-btn plan-recalc-btn"
              @click=${() => this._pressButton('recalculate_schedule')}>
              <ha-icon icon="mdi:refresh"></ha-icon>
              Recalculate
            </button>
          </div>
        </div>

        ${this._renderPlanControls()}

        ${todayChart ? html`
          <div class="plan-chart-label">Today <span class="plan-chart-date">${todayDate}</span></div>
          ${todayChart}
        ` : nothing}

        ${tomorrowChart ? html`
          <div class="plan-chart-label">Tomorrow <span class="plan-chart-date">${tomorrowDate}</span></div>
          ${tomorrowChart}
        ` : html`
          <div class="plan-chart-label plan-chart-label-muted">Tomorrow — prices not yet available</div>
        `}

        <!-- Legend -->
        <div class="plan-legend">
          <div class="plan-legend-item">
            <span class="plan-legend-dot" style="background: var(--vcc-success)"></span>
            <span>Charge</span>
          </div>
          <div class="plan-legend-item">
            <span class="plan-legend-dot" style="background: var(--vcc-warning)"></span>
            <span>Discharge</span>
          </div>
          <div class="plan-legend-item">
            <span class="plan-legend-dot" style="background: var(--vcc-disabled)"></span>
            <span>Idle</span>
          </div>
          <div class="plan-legend-item">
            <span class="plan-legend-dot" style="background: var(--vcc-pv-charge); opacity: 0.5"></span>
            <span>PV Charge</span>
          </div>
          <div class="plan-legend-item">
            <span class="plan-legend-dot plan-legend-dot-hatched" style="--legend-base: var(--vcc-success); --legend-hatch: var(--vcc-blocked-discharging)"></span>
            <span>Charge + Blocked Discharge</span>
          </div>
          <div class="plan-legend-item">
            <span class="plan-legend-dot plan-legend-dot-hatched" style="--legend-base: var(--vcc-warning); --legend-hatch: var(--vcc-blocked-charging)"></span>
            <span>Discharge + Blocked Charge</span>
          </div>
          <div class="plan-legend-item">
            <span class="plan-legend-dot plan-legend-dot-hatched" style="--legend-base: var(--vcc-blocked-both); --legend-hatch: var(--vcc-bg)"></span>
            <span>Blocked Both</span>
          </div>
          <div class="plan-legend-item">
            <span class="plan-legend-dot plan-legend-dot-current"></span>
            <span>Current</span>
          </div>
          ${ctCharge !== null ? html`
            <div class="plan-legend-item">
              <span class="plan-legend-line" style="border-color: var(--vcc-success)"></span>
              <span>Charge Threshold</span>
            </div>
          ` : nothing}
          ${ctDischarge !== null ? html`
            <div class="plan-legend-item">
              <span class="plan-legend-line" style="border-color: var(--vcc-warning)"></span>
              <span>Discharge Threshold</span>
            </div>
          ` : nothing}
        </div>
      </div>`;
  }

  // ── Main render ─────────────────────────────────────────

  render() {
    if (!this.hass || !this.config) return nothing;

    const modeEntity = this._state('select', 'control_mode');
    if (!modeEntity) {
      return html`
        <ha-card>
          <div class="card-content">
            <div class="warning">
              <ha-icon icon="mdi:alert-outline"></ha-icon>
              <span>
                Victron Charge Control entities not found.
                Check entity prefix: <code>${this.config.entity_prefix}</code>
              </span>
            </div>
          </div>
        </ha-card>`;
    }

    const action  = this._val('sensor', 'desired_action') || 'idle';
    const actMeta = ACTION_META[action] || ACTION_META.idle;
    const feedInStatus = this._val('sensor', 'grid_feed_in_status') || 'default';
    const feedInMeta = FEED_IN_META[feedInStatus] || FEED_IN_META.default;
    const view = this.config.view || 'settings';
    const viewTitle = view === 'plan' ? 'Plan' : (view === 'history' ? 'History' : 'Settings');
    const viewIcon = view === 'plan'
      ? 'mdi:calendar'
      : (view === 'history' ? 'mdi:chart-bar' : 'mdi:battery-charging-wireless');

    return html`
      <ha-card>
        <div class="card-header">
          <div class="header-title">
            <ha-icon .icon=${viewIcon}></ha-icon>
            <span>${viewTitle}</span>
          </div>
          <div class="header-badges">
            <div class="header-badge" data-feed-in=${feedInStatus}>
              <ha-icon .icon=${feedInMeta.icon}></ha-icon>
              <span>${feedInMeta.label}</span>
            </div>
            <div class="header-badge" data-action=${action}>
              <ha-icon .icon=${actMeta.icon}></ha-icon>
              <span>${actMeta.label}</span>
            </div>
          </div>
        </div>
        <div class="card-content">
          ${view === 'plan'
            ? this._renderPlanView()
            : (view === 'history' ? this._renderHistoryView() : this._renderControlsView())}
        </div>
      </ha-card>`;
  }

  // ── Styles ──────────────────────────────────────────────

  static get styles() {
    return css`
      /* ── Custom properties ─────────────────────── */
      :host {
        --vcc-accent:   var(--primary-color, #03a9f4);
        --vcc-bg:       var(--card-background-color, #fff);
        --vcc-border:   var(--divider-color, #e0e0e0);
        --vcc-text:     var(--primary-text-color, #212121);
        --vcc-text2:    var(--secondary-text-color, #757575);
        --vcc-success:  var(--success-color, #4caf50);
        --vcc-warning:  #ff6600;
        --vcc-error:    var(--error-color, #f44336);
        --vcc-info:     var(--info-color, #2196f3);
        --vcc-disabled: var(--disabled-color, #bdbdbd);
        --vcc-blocked-charging:    var(--success-color, #2e7d32);
        --vcc-blocked-discharging: var(--warning-color, #ef6c00);
        --vcc-blocked-both:        var(--error-color, #f44336);
        --vcc-pv-charge:           #ffb74d;
      }
      ha-card { overflow: hidden; }

      /* ── Header ────────────────────────────────── */
      .card-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 16px 16px 0;
      }
      .header-title {
        display: flex; align-items: center; gap: 8px;
        font-size: 1.0em; font-weight: 500; color: var(--vcc-text);
      }
      .header-title ha-icon { color: var(--vcc-accent); --mdc-icon-size: 22px; }

      .header-badges {
        display: flex; align-items: center; gap: 6px;
      }
      .header-badge {
        display: flex; align-items: center; gap: 3px;
        padding: 2px 8px; border-radius: 12px;
        font-size: 0.72em; font-weight: 600;
        background: rgba(158,158,158,0.12); color: var(--vcc-disabled);
      }
      .header-badge[data-action="charge"]    { background: rgba(76,175,80,0.12);  color: var(--vcc-success); }
      .header-badge[data-action="pv_charge"] { background: rgba(255,183,77,0.12); color: var(--vcc-pv-charge); }
      .header-badge[data-action="discharge"] { background: rgba(255,152,0,0.12);  color: var(--vcc-warning); }
      .header-badge[data-feed-in="default"]  { background: rgba(76,175,80,0.12);  color: var(--vcc-success); }
      .header-badge[data-feed-in="reduced"]  { background: rgba(255,152,0,0.12);  color: var(--vcc-warning); }
      .header-badge ha-icon { --mdc-icon-size: 13px; }

      /* ── Content ───────────────────────────────── */
      .card-content { padding: 12px 16px 16px; }

      /* ── Warning ───────────────────────────────── */
      .warning {
        display: flex; align-items: center; gap: 8px;
        padding: 16px; color: var(--vcc-warning); font-size: 0.9em;
      }
      .warning code {
        background: var(--vcc-border); padding: 2px 6px;
        border-radius: 4px; font-size: 0.9em;
      }

      /* ── Sections ──────────────────────────────── */
      .section { margin-bottom: 16px; }
      .section:last-of-type { margin-bottom: 8px; }
      .section-header {
        display: flex; align-items: center; gap: 6px;
        padding: 6px 0; font-size: 0.8em; font-weight: 600;
        color: var(--vcc-accent); text-transform: uppercase;
        letter-spacing: 0.5px;
        border-bottom: 1px solid var(--vcc-border); margin-bottom: 8px;
      }
      .section-header ha-icon { --mdc-icon-size: 16px; }
      .section-content { display: flex; flex-direction: column; gap: 0px; }

      /* ── Control rows ──────────────────────────── */
      .control-row {
        display: flex; align-items: center;
        justify-content: space-between;
        min-height: 36px; gap: 12px;
      }
      .control-row.slider-row {
        flex-direction: column;
        align-items: stretch;
        gap: 2px;
        min-height: auto;
      }
      .control-label {
        font-size: 0.88em; color: var(--vcc-text); flex-shrink: 0;
        width: 180px;
      }
      .control-row.slider-row > .control-label {
        width: auto;
      }
      .control-row.toggle-row > .control-label {
        flex: 1; width: auto; text-align: right;
      }
      .control-row.toggle-pair {
        gap: 16px;
      }
      .toggle-pair-item {
        display: flex; align-items: center; gap: 8px;
        flex: 1 1 0; min-width: 0;
      }
      .toggle-pair-item > .control-label {
        flex: 1; width: auto; text-align: right;
      }

      /* ── Mode selector ─────────────────────────── */
      .mode-group {
        display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 8px;
      }
      .mode-btn {
        display: flex; align-items: center; gap: 4px;
        padding: 6px 10px; border: 1px solid var(--vcc-border);
        border-radius: 8px; background: none; color: var(--vcc-text2);
        cursor: pointer; font-size: 0.78em; font-family: inherit;
        transition: all 0.15s ease;
      }
      .mode-btn ha-icon { --mdc-icon-size: 16px; }
      .mode-btn:hover { border-color: var(--vcc-accent); color: var(--vcc-accent); }

      .mode-btn[data-mode="off"].active            { background: rgba(158,158,158,0.12); border-color: var(--vcc-disabled); color: var(--vcc-disabled); font-weight: 600; }
      .mode-btn[data-mode="auto"].active            { background: rgba(33,150,243,0.12);  border-color: var(--vcc-info);     color: var(--vcc-info);     font-weight: 600; }
      .mode-btn[data-mode="manual"].active          { background: rgba(255,152,0,0.12);   border-color: var(--vcc-warning);  color: var(--vcc-warning);  font-weight: 600; }
      .mode-btn[data-mode="force_charge"].active    { background: rgba(76,175,80,0.12);   border-color: var(--vcc-success);  color: var(--vcc-success);  font-weight: 600; }
      .mode-btn[data-mode="force_discharge"].active { background: rgba(244,67,54,0.12);   border-color: var(--vcc-error);    color: var(--vcc-error);    font-weight: 600; }

      @media (max-width: 400px) {
        .mode-btn .mode-label { display: none; }
        .mode-btn { padding: 8px; }
      }

      /* ── Status row ────────────────────────────── */
      .status-row { display: flex; gap: 16px; flex-wrap: wrap; }
      .status-item {
        display: flex; align-items: center; gap: 4px;
        font-size: 0.88em; color: var(--vcc-text2);
      }
      .status-item ha-icon { --mdc-icon-size: 16px; }

      /* ── Slider ────────────────────────────────── */
      .slider-wrap {
        display: flex; align-items: center; gap: 8px;
        flex: 1; min-width: 0;
      }
      .slider-container {
        position: relative; flex: 1; min-width: 0;
        display: flex; align-items: center;
      }
      .slider-tooltip {
        position: absolute; bottom: 100%; margin-bottom: 6px;
        transform: translateX(-50%);
        background: var(--vcc-text, #212121); color: var(--vcc-bg, #fff);
        padding: 3px 8px; border-radius: 4px;
        font-size: 0.75em; font-weight: 600; white-space: nowrap;
        pointer-events: none; z-index: 1;
      }
      .slider-tooltip::after {
        content: ''; position: absolute;
        top: 100%; left: 50%; transform: translateX(-50%);
        border: 4px solid transparent;
        border-top-color: var(--vcc-text, #212121);
      }
      .slider-container input[type="range"] {
        flex: 1; min-width: 0; height: 4px; width: 100%;
        -webkit-appearance: none; appearance: none;
        background: var(--vcc-border); border-radius: 2px; outline: none;
        touch-action: none;
      }
      .slider-container input[type="range"]::-webkit-slider-thumb {
        -webkit-appearance: none; width: 16px; height: 16px;
        border-radius: 50%; background: var(--vcc-accent);
        cursor: pointer; border: 2px solid var(--vcc-bg);
        box-shadow: 0 1px 3px rgba(0,0,0,0.2);
        opacity: 0.5; transition: opacity 0.2s, transform 0.2s;
      }
      .slider-container input[type="range"].unlocked::-webkit-slider-thumb {
        opacity: 1; transform: scale(1.3);
      }
      .slider-container input[type="range"]::-moz-range-thumb {
        width: 12px; height: 12px; border-radius: 50%;
        background: var(--vcc-accent); cursor: pointer;
        border: 2px solid var(--vcc-bg);
        box-shadow: 0 1px 3px rgba(0,0,0,0.2);
        opacity: 0.5; transition: opacity 0.2s, transform 0.2s;
      }
      .slider-container input[type="range"].unlocked::-moz-range-thumb {
        opacity: 1; transform: scale(1.3);
      }
      .slider-hold-progress {
        position: absolute; bottom: -3px; left: 0; right: 0;
        height: 2px; border-radius: 1px; overflow: hidden;
        pointer-events: none;
      }
      .slider-hold-progress::after {
        content: ''; display: block; height: 100%;
        background: var(--vcc-accent); width: 0%;
        border-radius: 1px;
      }
      .slider-hold-progress.active::after {
        width: 100%; transition: width 1s linear;
      }
      .slider-hold-progress.done::after {
        width: 100%; background: var(--vcc-accent);
      }
      .slider-activated {
        animation: slider-pulse 0.2s ease;
      }
      @keyframes slider-pulse {
        0% { transform: scale(1); }
        50% { transform: scale(1.02); }
        100% { transform: scale(1); }
      }
      .slider-value {
        font-size: 0.82em; font-weight: 500; color: var(--vcc-text);
        min-width: 70px; text-align: right; white-space: nowrap;
      }

      /* ── Hour chips ────────────────────────────── */
      .blocked-group { margin-bottom: 10px; }
      .blocked-group:last-child { margin-bottom: 0; }
      .blocked-label {
        display: block; font-size: 0.82em;
        color: var(--vcc-text2); margin-bottom: 6px;
      }
      .hour-grid {
        display: grid; grid-template-columns: repeat(12, 1fr); gap: 3px;
      }
      .hour-chip {
        display: flex; align-items: center; justify-content: center;
        padding: 4px 0; border: 1px solid var(--vcc-border);
        border-radius: 4px; background: none; color: var(--vcc-text2);
        cursor: pointer; font-size: 0.72em; font-family: inherit;
        transition: all 0.15s ease;
      }
      .hour-chip:hover { border-color: var(--vcc-accent); color: var(--vcc-accent); }
      .hour-chip.blocked {
        background: rgba(244,67,54,0.12); border-color: var(--vcc-error);
        color: var(--vcc-error); font-weight: 600;
      }
      .hour-chip.replan {
        background: rgba(33,150,243,0.12); border-color: var(--vcc-info);
        color: var(--vcc-info); font-weight: 600;
      }
      @media (max-width: 350px) {
        .hour-grid { grid-template-columns: repeat(8, 1fr); }
      }

      /* ── Action buttons ────────────────────────── */
      .actions {
        display: flex; gap: 8px; padding-top: 8px; flex-wrap: wrap;
      }
      .action-btn {
        display: flex; align-items: center; gap: 6px;
        padding: 8px 14px; border: 1px solid var(--vcc-border);
        border-radius: 8px; background: none; color: var(--vcc-text);
        cursor: pointer; font-size: 0.82em; font-family: inherit;
        transition: all 0.15s ease;
      }
      .action-btn:hover { background: rgba(0,0,0,0.04); }
      .action-btn.primary {
        background: var(--vcc-accent); border-color: var(--vcc-accent); color: #fff;
      }
      .action-btn.primary:hover { opacity: 0.9; }
      .action-btn ha-icon { --mdc-icon-size: 16px; }

      /* ── Plan chart ────────────────────────────── */
      .plan-chart-container {
        display: flex; flex-direction: column; gap: 12px;
      }
      .plan-chart {
        width: 100%; height: auto;
        font-family: inherit;
      }
      .plan-axis-label {
        font-size: 16px;
        fill: var(--vcc-text2, #757575);
      }
      .plan-axis-unit {
        font-size: 15px;
        fill: var(--vcc-text2, #757575);
      }
      .plan-threshold-label {
        font-size: 11px;
        font-weight: 700;
      }
      .threshold-line-group {
        cursor: grab; touch-action: none;
        -webkit-user-select: none; user-select: none;
      }
      .threshold-hit-area,
      .threshold-visible-line,
      .plan-threshold-label {
        touch-action: none;
        -webkit-user-select: none; user-select: none;
      }
      .threshold-hit-area {
        pointer-events: stroke;
      }
      .threshold-line-group .threshold-visible-line {
        transition: stroke-width 0.2s;
      }
      .threshold-line-group.threshold-holding .threshold-visible-line {
        stroke-width: 2.5;
        animation: threshold-pulse 1s linear;
      }
      .threshold-line-group.threshold-unlocked .threshold-visible-line {
        stroke-width: 3;
      }
      .threshold-line-group.threshold-unlocked {
        cursor: ns-resize;
      }
      :host(.threshold-drag-active) .plan-chart-container {
        touch-action: none;
      }
      @keyframes threshold-pulse {
        0% { stroke-opacity: 0.5; }
        100% { stroke-opacity: 1; }
      }
      .plan-current-hour {
        font-weight: 700;
        fill: var(--vcc-accent, #03a9f4);
      }
      .plan-bar-group {
        cursor: pointer;
      }
      .plan-bar-group[data-past="true"] {
        cursor: default;
      }
      .plan-bar-hit {
        pointer-events: all;
      }
      .plan-pv-column {
        pointer-events: none;
      }
      .plan-picker-bg {
        filter: drop-shadow(0 1px 2px rgba(0,0,0,0.15));
      }
      .plan-picker-title {
        font-size: 12px;
        font-weight: 600;
        fill: var(--vcc-text, #212121);
        pointer-events: none;
        user-select: none;
      }
      .plan-picker-btn { cursor: pointer; }
      .plan-picker-btn:hover rect { opacity: 0.85; }
      .plan-picker-label {
        font-size: 11px;
        font-weight: 600;
        fill: var(--vcc-text, #212121);
        pointer-events: none;
        user-select: none;
      }
      .plan-picker-label-active {
        fill: #fff;
      }
      .plan-bar-tooltip .plan-tooltip-time {
        font-size: 16px;
        font-weight: 600;
        fill: var(--vcc-text, #212121);
      }
      .plan-bar-tooltip .plan-tooltip-price {
        font-size: 16px;
        font-weight: 700;
        fill: var(--vcc-text, #212121);
      }
      .plan-legend {
        display: flex; flex-wrap: wrap; gap: 12px;
        justify-content: center;
        font-size: 0.78em; color: var(--vcc-text2);
      }
      .plan-legend-item {
        display: flex; align-items: center; gap: 4px;
      }
      .plan-legend-dot {
        width: 10px; height: 10px; border-radius: 2px;
        flex-shrink: 0;
      }
      .plan-legend-dot-hatched {
        background:
          repeating-linear-gradient(
            135deg,
            transparent 0 5px,
            var(--legend-hatch, var(--vcc-bg, #fff)) 5px 7px,
            transparent 7px 10px
          ),
          var(--legend-base, var(--vcc-error, #f44336));
      }
      .plan-legend-dot-current {
        background: none;
        border: 1.5px dashed var(--vcc-accent, #03a9f4);
      }
      .plan-legend-line {
        width: 16px; height: 0;
        border-top: 2px dashed;
        flex-shrink: 0;
        align-self: center;
      }
      .plan-chart-label {
        font-size: 0.85em;
        font-weight: 600;
        color: var(--vcc-text, #212121);
        padding: 4px 0 0;
      }
      .plan-chart-label-muted {
        color: var(--vcc-text2, #757575);
        font-weight: 400;
        font-style: italic;
      }
      .plan-chart-date {
        font-weight: 400;
        color: var(--vcc-text2, #757575);
        font-size: 0.9em;
      }
      .plan-toolbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 0 4px;
      }
      .plan-toolbar-right {
        display: flex;
        flex-direction: row;
        align-items: center;
        gap: 8px;
      }
      .plan-recalc-btn {
        font-size: 0.78em;
        padding: 5px 10px;
      }
      .plan-recalc-btn:hover {
        border-color: var(--vcc-accent, #03a9f4);
        color: var(--vcc-accent, #03a9f4);
      }
      .plan-last-update {
        font-size: 0.75em;
        color: var(--vcc-text2, #757575);
      }
      .plan-current-price {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 0.95em;
        color: var(--vcc-text, #212121);
      }
      .plan-current-price ha-icon {
        --mdc-icon-size: 18px;
        color: var(--vcc-text2, #757575);
      }
      .plan-recalc-btn {
        font-size: 0.78em;
        padding: 5px 10px;
      }
      .plan-recalc-btn:hover {
        border-color: var(--vcc-accent, #03a9f4);
        color: var(--vcc-accent, #03a9f4);
      }
      .plan-controls {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 4px 0 8px;
        flex-wrap: nowrap;
      }
      .plan-control-toggle {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 0.82em;
        color: var(--vcc-text, #212121);
        white-space: nowrap;
        flex: 0 0 auto;
      }
      .plan-control-toggle ha-icon {
        --mdc-icon-size: 16px;
        color: var(--vcc-text2, #757575);
      }
      .plan-control-label {
        color: var(--vcc-text, #212121);
      }

      /* ── Cost chart ────────────────────────────── */
      .history-container {
        display: flex;
        flex-direction: column;
        gap: 12px;
      }
      .history-toolbar {
        display: flex;
        flex-direction: column;
        align-items: stretch;
        gap: 8px;
      }
      .cost-range-group {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 4px;
      }
      .cost-range-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 4px;
        min-width: 0;
        padding: 7px 6px;
        border: 1px solid var(--vcc-border);
        border-radius: 8px;
        background: none;
        color: var(--vcc-text2);
        cursor: pointer;
        font-size: 0.78em;
        font-family: inherit;
        transition: all 0.15s ease;
      }
      .cost-range-btn ha-icon {
        --mdc-icon-size: 16px;
      }
      .cost-range-btn:hover {
        border-color: var(--vcc-accent);
        color: var(--vcc-accent);
      }
      .cost-range-btn.active {
        background: rgba(33,150,243,0.12);
        border-color: var(--vcc-info);
        color: var(--vcc-info);
        font-weight: 600;
      }
      .cost-range-btn span {
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .cost-mode-group {
        display: flex;
        gap: 4px;
      }
      .cost-mode-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 3px;
        padding: 7px 10px;
        border: 1px solid var(--vcc-border);
        border-radius: 8px;
        background: none;
        color: var(--vcc-text2);
        cursor: pointer;
        font-size: 0.78em;
        font-family: inherit;
        transition: all 0.15s ease;
      }
      .cost-mode-btn ha-icon {
        --mdc-icon-size: 16px;
      }
      .cost-mode-btn:hover {
        border-color: var(--vcc-accent);
        color: var(--vcc-accent);
      }
      .cost-mode-btn.active {
        background: rgba(33,150,243,0.12);
        border-color: var(--vcc-info);
        color: var(--vcc-info);
        font-weight: 600;
      }
      .cost-period-nav {
        display: grid;
        grid-template-columns: 34px minmax(0, 1fr) 34px 34px;
        align-items: center;
        gap: 6px;
      }
      .cost-period-btn,
      .cost-refresh-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 34px;
        height: 32px;
        border: 1px solid var(--vcc-border);
        border-radius: 8px;
        background: none;
        color: var(--vcc-text);
        cursor: pointer;
        font-family: inherit;
        transition: all 0.15s ease;
      }
      .cost-period-btn:hover:not(:disabled),
      .cost-refresh-btn:hover {
        border-color: var(--vcc-accent);
        color: var(--vcc-accent);
        background: rgba(0,0,0,0.04);
      }
      .cost-period-btn:disabled {
        opacity: 0.38;
        cursor: default;
        pointer-events: none;
      }
      .cost-period-btn ha-icon,
      .cost-refresh-btn ha-icon {
        --mdc-icon-size: 18px;
      }
      .cost-period-label {
        min-width: 0;
        text-align: center;
        color: var(--vcc-text);
        font-size: 0.88em;
        font-weight: 600;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .cost-summary {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 6px;
      }
      .cost-summary-item {
        min-width: 0;
        padding: 8px 9px;
        border: 1px solid var(--vcc-border);
        border-radius: 8px;
      }
      .cost-summary-item span {
        display: block;
        color: var(--vcc-text2);
        font-size: 0.72em;
        margin-bottom: 2px;
      }
      .cost-summary-item strong {
        display: block;
        color: var(--vcc-text);
        font-size: 0.9em;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .cost-summary-item.cost strong,
      .cost-summary-item.negative strong {
        color: var(--vcc-error);
      }
      .cost-summary-item.revenue strong,
      .cost-summary-item.positive strong {
        color: var(--vcc-success);
      }
      .cost-chart {
        width: 100%;
        height: auto;
        font-family: inherit;
      }
      .cost-axis-label {
        font-size: 16px;
        fill: var(--vcc-text2, #757575);
      }
      .cost-axis-unit {
        font-size: 16px;
        fill: var(--vcc-text2, #757575);
      }
      .cost-bar-group {
        cursor: pointer;
      }
      .cost-bar-tooltip .cost-tooltip-time {
        font-size: 16px;
        font-weight: 600;
        fill: var(--vcc-text, #212121);
      }
      .cost-bar-tooltip .cost-tooltip-cost {
        font-size: 16px;
        font-weight: 700;
        fill: var(--vcc-error, #f44336);
      }
      .cost-bar-tooltip .cost-tooltip-revenue {
        font-size: 16px;
        font-weight: 700;
        fill: var(--vcc-success, #4caf50);
      }
      .cost-loading {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 16px;
        color: var(--vcc-text2);
        font-size: 0.9em;
      }
      .cost-loading ha-icon {
        --mdc-icon-size: 18px;
      }
      @media (max-width: 420px) {
        .cost-range-btn {
          gap: 3px;
          padding: 7px 4px;
          font-size: 0.74em;
        }
        .cost-range-btn ha-icon {
          --mdc-icon-size: 14px;
        }
        .cost-mode-btn {
          padding: 6px 7px;
          font-size: 0.74em;
        }
        .cost-mode-btn ha-icon {
          --mdc-icon-size: 14px;
        }
        .cost-period-nav {
          grid-template-columns: 32px minmax(0, 1fr) 32px 32px;
          gap: 5px;
        }
        .cost-period-btn,
        .cost-refresh-btn {
          width: 32px;
          height: 31px;
        }
        .cost-period-label {
          font-size: 0.82em;
        }
        .cost-summary {
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 4px;
        }
        .cost-summary-item {
          padding: 7px 5px;
        }
        .cost-summary-item span {
          font-size: 0.68em;
        }
        .cost-summary-item strong {
          font-size: 0.78em;
        }
      }
    `;
  }
}

// ────────────────────────────────────────────────────────────
// Card Editor
// ────────────────────────────────────────────────────────────

class VictronChargeControllerCardEditor extends LitElement {

  static get properties() {
    return {
      hass: { type: Object },
      config: { type: Object },
    };
  }

  setConfig(config) {
    this.config = { ...config };
  }

  _changed(key, value) {
    this.config = { ...this.config, [key]: value };
    this.dispatchEvent(
      new CustomEvent('config-changed', { detail: { config: this.config } }),
    );
  }

  render() {
    if (!this.config) return nothing;
    return html`
      <div class="editor">
        <div class="row">
          <label for="view">View</label>
          <select id="view"
            .value=${this.config.view || 'settings'}
            @change=${(e) => this._changed('view', e.target.value)}
          >
            <option value="settings" ?selected=${(this.config.view || 'settings') === 'settings'}>Settings</option>
            <option value="plan" ?selected=${this.config.view === 'plan'}>Plan</option>
            <option value="history" ?selected=${this.config.view === 'history'}>History</option>
          </select>
          <small>Choose which view this card displays</small>
        </div>
      </div>`;
  }

  static get styles() {
    return css`
      .editor { padding: 16px; }
      .row { display: flex; flex-direction: column; margin-bottom: 12px; }
      label { font-size: 0.85em; font-weight: 500; margin-bottom: 4px; color: var(--primary-text-color); }
      input, select {
        padding: 8px; border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: 4px; font-size: 0.9em; font-family: inherit;
      }
      small { font-size: 0.75em; color: var(--secondary-text-color); margin-top: 4px; }
    `;
  }
}

// ────────────────────────────────────────────────────────────
// Registration
// ────────────────────────────────────────────────────────────

function defineCardElements() {
  if (!window.customElements.get(CARD_TAG)) {
    window.customElements.define(CARD_TAG, VictronChargeControllerCard);
  }
  if (!window.customElements.get(EDITOR_TAG)) {
    window.customElements.define(EDITOR_TAG, VictronChargeControllerCardEditor);
  }

  window.customCards = window.customCards || [];
  if (!window.customCards.some((card) => card.type === CARD_TAG)) {
    window.customCards.push({
      type: CARD_TAG,
      name: 'Victron Charge Controller',
      description: 'Control and monitor your Victron ESS charge controller',
      preview: true,
    });
  }

  console.info(
    `%c VICTRON-CHARGE-CONTROLLER-CARD %c v${CARD_VERSION} `,
    'color: white; background: #03a9f4; font-weight: 700; border-radius: 4px 0 0 4px; padding: 2px 6px;',
    'color: #03a9f4; background: transparent; font-weight: 700; border: 1px solid #03a9f4; border-radius: 0 4px 4px 0; padding: 2px 6px;',
  );
}

async function registerCard() {
  // This module is auto-loaded by the integration via add_extra_js_url, which
  // makes Home Assistant's index page import it in a race with HA's own core
  // bundle. Recent HA frontends replace window.customElements with a scoped
  // custom-element-registry polyfill during boot; elements defined before that
  // swap are stranded in the discarded native registry and Lovelace reports
  // "Custom element doesn't exist". The HA index page sets
  // window.customPanelJS synchronously before extra modules are imported, so
  // its presence tells us we are inside HA and must wait until HA's root
  // element resolves through the *current* registry (i.e. the final registry
  // is installed) before defining ours. window.customElements is re-read on
  // every poll on purpose — a stored reference would keep pointing at the
  // replaced registry.
  if (window.customPanelJS !== undefined || window.hassConnection !== undefined) {
    const deadline = Date.now() + 60000;
    while (!window.customElements.get('home-assistant') && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
  }
  defineCardElements();
}

registerCard();
