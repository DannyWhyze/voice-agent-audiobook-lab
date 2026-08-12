const KNOB_DRAG_RANGE_PX = 150;

// Each entry in `defs` describes one knob:
//   key            -- params[key] this knob controls
//   label, unit, decimals, min, max, step -- display/range basics
//   toParam(displayValue) / fromParam(paramValue) -- optional conversion
//     between the on-screen value and the stored params value (default:
//     identity). E.g. a knob showing "75%" storing params.x = 0.75.
//   linkedKey / linkedRatio -- optional: params[linkedKey] is kept at
//     params[key] * linkedRatio on every change (Reverb's coupled diffusion
//     coefficients).
//   formatValue(displayValue) -- optional custom text formatter, overrides
//     the default `displayValue.toFixed(decimals) + unit`.
//   roundDecimals -- decimal places to round the snapped value to, cleaning
//     up floating-point noise from step-snapping (default 3).
export function buildKnobGrid({ container, defs, params, onChange }) {
  const knobRefreshFns = [];

  for (const def of defs) {
    const toParam = def.toParam || ((displayValue) => displayValue);
    const fromParam = def.fromParam || ((paramValue) => paramValue);
    const roundFactor = 10 ** (def.roundDecimals ?? 3);

    const unit = document.createElement("div");
    unit.className = "compressor-knob-unit";

    const label = document.createElement("div");
    label.className = "compressor-stepper-label";
    label.textContent = def.label;
    unit.appendChild(label);

    const knob = document.createElement("div");
    knob.className = "compressor-knob";
    knob.tabIndex = 0;

    const pointer = document.createElement("div");
    pointer.className = "compressor-knob-pointer";
    knob.appendChild(pointer);
    unit.appendChild(knob);

    const valueSpan = document.createElement("span");
    valueSpan.className = "compressor-stepper-value";
    unit.appendChild(valueSpan);

    function angleForValue(displayValue) {
      const fraction = (displayValue - def.min) / (def.max - def.min);
      return -135 + fraction * 270;
    }

    function refreshValue() {
      const displayValue = fromParam(params[def.key]);
      valueSpan.textContent = def.formatValue
        ? def.formatValue(displayValue)
        : displayValue.toFixed(def.decimals) + def.unit;
      pointer.style.transform = `translateX(-50%) rotate(${angleForValue(displayValue)}deg)`;
    }
    refreshValue();
    knobRefreshFns.push(refreshValue);

    function setValue(newDisplayValue) {
      const clamped = Math.max(def.min, Math.min(def.max, newDisplayValue));
      const snapped = Math.round(clamped / def.step) * def.step;
      params[def.key] = toParam(Math.round(snapped * roundFactor) / roundFactor);
      if (def.linkedKey) {
        params[def.linkedKey] = params[def.key] * def.linkedRatio;
      }
      refreshValue();
      onChange();
    }

    let dragStartY = 0;
    let dragStartDisplayValue = 0;

    knob.addEventListener("pointerdown", (event) => {
      knob.setPointerCapture(event.pointerId);
      knob.classList.add("dragging");
      dragStartY = event.clientY;
      dragStartDisplayValue = fromParam(params[def.key]);
      event.preventDefault();
    });

    knob.addEventListener("pointermove", (event) => {
      if (!knob.classList.contains("dragging")) return;
      const deltaY = dragStartY - event.clientY;
      const fraction = deltaY / KNOB_DRAG_RANGE_PX;
      setValue(dragStartDisplayValue + fraction * (def.max - def.min));
    });

    function endDrag(event) {
      if (knob.classList.contains("dragging")) {
        knob.classList.remove("dragging");
        knob.releasePointerCapture(event.pointerId);
      }
    }
    knob.addEventListener("pointerup", endDrag);
    knob.addEventListener("pointercancel", endDrag);

    knob.addEventListener("keydown", (event) => {
      const currentDisplayValue = fromParam(params[def.key]);
      if (event.key === "ArrowUp" || event.key === "ArrowRight") {
        event.preventDefault();
        setValue(currentDisplayValue + def.step);
      } else if (event.key === "ArrowDown" || event.key === "ArrowLeft") {
        event.preventDefault();
        setValue(currentDisplayValue - def.step);
      }
    });

    container.appendChild(unit);
  }

  return knobRefreshFns;
}
