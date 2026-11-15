const assert = require("node:assert/strict"),
  fs = require("node:fs"),
  vm = require("node:vm");
const registrations = {};
const context = {
  window: {
    locals: {
      "POS User Store": { row1: { store: "A" }, row2: { store: "B" } },
    },
  },
  frappe: { ui: { form: { on: (dt, h) => (registrations[dt] = h) } } },
  requestAnimationFrame() {},
  document: {},
  __: (x) => x,
};
vm.createContext(context);
vm.runInContext(
  fs.readFileSync(__dirname + "/rms_form_experience.js", "utf8"),
  context
);
const UX = context.window.RMSFormExperience;
assert.equal(Object.keys(registrations).length, 24);
const registered = {};
const frm = {
  doctype: "POS User",
  doc: { stores: [{ store: "A" }, { store: "B" }] },
  fields_dict: {
    stores: {},
    allowed_brands: {},
    allowed_order_types: {},
    allowed_preparation_areas: {},
  },
  set_query: (name, table, fn) => (registered[table + "." + name] = fn),
};
UX.setupQueries(frm);
assert.equal(
  registered["stores.pos_profile"]({}, "POS User Store", "row1").filters
    .stores[0],
  "A"
);
assert.equal(
  registered["stores.pos_profile"]({}, "POS User Store", "row2").filters
    .stores[0],
  "B",
  "each row uses its own store"
);
assert.equal(
  registered["allowed_preparation_areas.preparation_area"]().filters.kds_only,
  1
);
frm.doc.stores = [{ store: "C" }];
assert.equal(
  registered["allowed_brands.restaurant_brand"]().filters.stores[0],
  "C",
  "scope must follow current document state"
);
const control = (name, required = true, hidden = false, readonly = false) => ({
  df: { fieldname: name, reqd: required, hidden, read_only: readonly },
  wrapper: { getClientRects: () => [{}] },
  get_status: () => (hidden ? "None" : "Write"),
});
const test = {
  doc: { zero: 0, empty: "", rows: [] },
  fields: [
    control("zero"),
    control("empty"),
    control("rows"),
    control("hidden", true, true),
    control("readonly", true, false, true),
  ],
};
assert.deepEqual(
  Array.from(UX.missingFields(test), (c) => c.df.fieldname),
  ["empty", "rows"]
);
assert.equal(
  test.doc.zero,
  0,
  "UX must not normalize or clear business values"
);
console.log(
  "PASS: RMS parent form coverage, per-row scoped links, live scope changes and zero-safe required-field guidance."
);

(async () => {
  const group = {
    doc: { allow_collapse: 0, collapsed_by_default: 1 },
    async set_value(key, value) {
      this.doc[key] = value;
    },
  };
  await registrations["Modifier Group"].allow_collapse(group);
  assert.equal(
    group.doc.collapsed_by_default,
    0,
    "disabling collapse must not leave an impossible hidden default"
  );
  const ingredients = [{ item: "FLOUR", qty: 1 }];
  const product = {
    doc: { with_recipe: 0, recipe: ingredients, additional_recipe: [] },
    async set_value(key, value) {
      this.doc[key] = value;
    },
  };
  let explained = false;
  context.frappe.msgprint = () => {
    explained = true;
  };
  await registrations["Selling Product"].with_recipe(product);
  assert.equal(product.doc.with_recipe, 1);
  assert.equal(
    product.doc.recipe,
    ingredients,
    "turning off a populated recipe must preserve ingredient rows"
  );
  assert.equal(
    explained,
    true,
    "show the user how to disable a populated recipe"
  );
  console.log(
    "PASS: dependent collapse flags and recipe edits preserve a valid configuration without deleting ingredient rows."
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

const classList = (...names) => {
  const values = new Set(names);
  return {
    contains: (name) => values.has(name),
    add: (...items) => items.forEach((x) => values.add(x)),
    toggle(name, state) {
      if (state) values.add(name);
      else values.delete(name);
    },
  };
};
const panel = (name, hidden = false) => ({
  df: { fieldname: name, label: name, hidden },
  wrapper: { classList: classList(), getClientRects: () => [] },
  is_collapsed: () => false,
});
const first = panel("first"),
  second = panel("second"),
  technical = panel("technical", true);
const buttons = ["first", "second"].map((name) => ({
  dataset: { section: name },
  attributes: {},
  setAttribute(k, v) {
    this.attributes[k] = v;
  },
  removeAttribute(k) {
    delete this.attributes[k];
  },
}));
const panes = {
  layout: { sections: [first, second, technical] },
  __rmsExperience: { nav: { querySelectorAll: () => buttons } },
};
UX.selectSection(panes, first);
assert.equal(first.wrapper.classList.contains("rms-form-pane-hidden"), false);
assert.equal(second.wrapper.classList.contains("rms-form-pane-hidden"), true);
assert.equal(buttons[0].attributes["aria-selected"], "true");
UX.selectSection(panes, second);
assert.equal(first.wrapper.classList.contains("rms-form-pane-hidden"), true);
assert.equal(second.wrapper.classList.contains("rms-form-pane-hidden"), false);
assert.equal(buttons[0].attributes["aria-selected"], "false");
assert.equal(buttons[1].attributes["aria-selected"], "true");
UX.selectSection(panes, technical);
assert.equal(
  panes.__rmsExperience.active,
  "second",
  "technical/dependency-hidden sections cannot be activated"
);
let forwarded;
panes.fields_dict = { required: { section: first } };
panes.scroll_to_field = function (...args) {
  forwarded = args;
  return true;
};
UX.installFieldReveal(panes);
assert.equal(panes.scroll_to_field("required", 123), true);
assert.equal(
  panes.__rmsExperience.active,
  "first",
  "native validation scroll opens the owning section"
);
assert.equal(forwarded[1], 123, "native focus options pass through");
const hiddenPaneControl = control("empty");
hiddenPaneControl.wrapper.getClientRects = () => [];
hiddenPaneControl.section = second;
assert.equal(
  UX.missingFields({ doc: { empty: "" }, fields: [hiddenPaneControl] }).length,
  1,
  "presentation-hidden sections still contribute required fields"
);
console.log(
  "PASS: one section at a time, selected-state accessibility, native validation reveal and required guidance across hidden panes."
);
