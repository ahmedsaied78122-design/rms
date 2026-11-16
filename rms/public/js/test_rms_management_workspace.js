const assert = require("node:assert/strict"),
  fs = require("node:fs"),
  vm = require("node:vm");
const classes = new Set(["rms-studio-active", "rms-management"]);
const context = {
  window: { matchMedia: () => ({ matches: false }) },
  document: {
    body: {
      classList: {
        contains: (k) => classes.has(k),
        remove: (k) => classes.delete(k),
      },
    },
  },
};
vm.createContext(context);
vm.runInContext(
  fs.readFileSync(__dirname + "/rms_management_workspace.js", "utf8"),
  context
);
const Studio = context.window.RMSWorkspaceStudio;
const data = {
  labels: ["Week 1", "Week 2"],
  datasets: [
    { name: "Revenue", values: [120, 180] },
    { name: "Refunds", values: [5, 8] },
  ],
};
const tooltip = { formatTooltipY: (value) => "EGP " + value };
const select = () => {};
const original = {
  type: "bar",
  data,
  tooltipOptions: tooltip,
  isNavigable: true,
  onSelect: select,
  barOptions: { stacked: true },
  colors: ["pink"],
};
const before = JSON.stringify(original);
const themed = Studio.chartOptions(original, true);
assert.equal(
  themed.data,
  data,
  "chart presentation must keep the original dataset and values"
);
assert.equal(themed.type, "bar");
assert.equal(themed.tooltipOptions, tooltip);
assert.equal(themed.onSelect, select);
assert.equal(
  themed.barOptions.stacked,
  true,
  "configured stacked bars stay stacked"
);
assert.equal(themed.animate, false, "reduced motion disables chart animation");
assert.equal(
  themed.disableEntryAnimation,
  true,
  "resize cannot overlap an asynchronous SVG replacement"
);
assert.equal(
  JSON.stringify(original),
  before,
  "theme must not mutate native options or saved preferences"
);
assert.notEqual(themed.colors[0], "pink");
for (const type of ["bar", "line", "pie", "donut", "percentage"]) {
  const english = ["Expense", "Net Profit/Loss", "Refunds", "Overdue"];
  const arabic = ["نفقة", "صافي الربح / الخسارة", "مرتجعات", "متأخر"];
  const chart = (names) => ({
    type,
    data: {
      labels: names,
      datasets: names.map((name) => ({ name, values: [-5526.35, 5526.35] })),
    },
  });
  const en = Studio.chartOptions(chart(english));
  const ar = Studio.chartOptions(chart(arabic));
  assert.deepEqual(
    en.colors,
    ar.colors,
    type + " colors must survive translation"
  );
  assert.equal(en.colors[0], "#24785e");
  assert.equal(en.colors[1], "#bed865");
  assert.equal(
    new Set(en.colors).size,
    4,
    "distinct series must stay distinguishable"
  );
  const renamed = chart(["A", "B", "C", "D"]);
  assert.deepEqual(Studio.chartOptions(renamed).colors, en.colors);
  assert.deepEqual(
    en.data,
    chart(english).data,
    "signed financial values must stay intact"
  );
}
const line = Studio.chartOptions({
  type: "line",
  data,
  lineOptions: { regionFill: 0, hideDots: 1 },
});
assert.equal(
  line.lineOptions.regionFill,
  0,
  "explicit chart line options are respected"
);
const heatmap = Studio.chartOptions({
  type: "heatmap",
  data: { dataPoints: {}, start: new Date(), end: new Date() },
});
assert.equal(heatmap.colors.length, 5);
assert.equal(heatmap.type, "heatmap");
const pie = Studio.chartOptions({
  type: "pie",
  data: {
    labels: ["Revenue", "Refunds", "Services"],
    datasets: [{ values: [50, 10, 40] }],
  },
});
assert.equal(
  pie.colors.length,
  3,
  "pie categories need separate colors even when there is only one dataset"
);
assert.equal(new Set(pie.colors).size, 3);
assert.equal(Studio.directoryMatch("طلبَات نُقطة البيع", "طلبات بيع"), true);
assert.equal(Studio.directoryMatch("إعدادات الكاشير", "اعدادات"), true);
assert.equal(
  Studio.directoryMatch("/app/pos-profile Cashier Profiles", "POS PROFILE"),
  true
);
assert.equal(Studio.directoryMatch("Products and menus", "cashier"), false);
assert.equal(Studio.directoryMatch("Any screen", "  "), true);
assert.equal(Studio.group({ name: "Accounting", public: 1 }), "Business");
assert.equal(Studio.group({ name: "My page", public: 0 }), "Personal");
assert.equal(
  Studio.group({ name: "Unknown installed module", public: 1 }),
  "Business"
);
assert.ok(
  !Studio.icon("<script>").includes("<script>"),
  "icons must come only from the fixed glyph catalog"
);
let restored = false,
  deleted = false,
  badgeRemoved = 0,
  rootRemoved = false;
const badge = {
  remove() {
    badgeRemoved++;
  },
};
const widget = {
  querySelectorAll: () => [],
  querySelector: (selector) =>
    selector === "[data-rms-widget-badge]" ? badge : null,
  classList: { remove() {} },
  remove() {
    deleted = true;
  },
};
const marker = {
  isConnected: true,
  replaceWith(value) {
    assert.equal(value, widget);
    restored = true;
  },
};
const studio = Object.create(Studio.prototype);
studio.portals = new Map([[widget, marker]]);
studio.sections = new Map();
studio.root = {
  remove() {
    rootRemoved = true;
  },
};
studio.restore();
assert.ok(restored && rootRemoved);
assert.equal(deleted, false);
assert.equal(badgeRemoved, 1);
assert.equal(studio.portals.size, 0);
assert.equal(
  classes.has("rms-studio-active"),
  false,
  "restoring the editor must remove the studio layout state"
);
marker.isConnected = false;
studio.portals.set(widget, marker);
studio.restore();
assert.equal(
  deleted,
  true,
  "a disposed native block must not leave a ghost card"
);
context.window.frappe = {
  widget: {
    widget_factory: {
      chart: class {
        get_chart_args() {
          return original;
        }
      },
    },
  },
};
const helper = new Studio({});
const Wrapped = context.window.frappe.widget.widget_factory.chart;
helper.installCharts();
assert.equal(
  context.window.frappe.widget.widget_factory.chart,
  Wrapped,
  "chart integration is installed once"
);
assert.equal(new Wrapped().get_chart_args().data, data);
classes.delete("rms-management");
assert.equal(
  new Wrapped().get_chart_args(),
  original,
  "non-Management consumers receive untouched chart options"
);
console.log(
  "PASS: chart values, types, formatting, callbacks, explicit options, scoped integration, private modules and reversible widget ownership."
);

(async () => {
  let released = 0,
    synchronized = 0;
  const bridge = Object.create(Studio.prototype);
  bridge.root = {};
  bridge.releaseWidgets = () => released++;
  bridge.shell = { scheduleSync: () => synchronized++ };
  context.window.rmsManagementUI = { studio: bridge };
  const receiver = {
    token: 7,
    save_page(value) {
      assert.equal(this.token, 7);
      assert.equal(value, "draft");
      assert.equal(bridge.suspendPortals, true);
      assert.equal(released, 1);
      return Promise.resolve(false);
    },
  };
  bridge.installNativeSave(receiver);
  const wrapped = receiver.save_page;
  bridge.installNativeSave(receiver);
  assert.equal(receiver.save_page, wrapped, "save must be wrapped once");
  assert.equal(
    await receiver.save_page("draft"),
    false,
    "native no-change result must survive"
  );
  assert.equal(bridge.suspendPortals, false);
  assert.equal(synchronized, 1);
  const failure = new Error("native save failure");
  const rejected = { save_page: () => Promise.reject(failure) };
  bridge.installNativeSave(rejected);
  await assert.rejects(rejected.save_page(), (error) => error === failure);
  assert.equal(
    bridge.suspendPortals,
    false,
    "failed saves must release the rendering guard"
  );
  const throwing = {
    save_page: () => {
      throw failure;
    },
  };
  bridge.installNativeSave(throwing);
  assert.throws(
    () => throwing.save_page(),
    (error) => error === failure
  );
  assert.equal(bridge.suspendPortals, false);
  bridge.root = null;
  const inactive = { save_page: () => 42 };
  bridge.installNativeSave(inactive);
  assert.equal(
    inactive.save_page(),
    42,
    "inactive RMS must leave native saving unchanged"
  );

  let inserted = null;
  const ws = {
    is_read_only: true,
    editor: { blocks: { insert: (...args) => (inserted = args) } },
  };
  context.frappe = { workspace: ws };
  let chosen = "chart";
  bridge.editToolbar = { querySelector: () => ({ value: chosen }) };
  bridge.addBlock();
  assert.equal(inserted, null, "read-only workspaces cannot add blocks");
  ws.is_read_only = false;
  bridge.addBlock();
  assert.equal(inserted[0], "chart");
  assert.equal(inserted[1].col, 12);
  inserted = null;
  chosen = "unregistered_tool";
  bridge.addBlock();
  assert.equal(
    inserted,
    null,
    "only existing supported widget tools may be inserted"
  );
  console.log(
    "PASS: native save ownership, binding, false results, error recovery, inactive behavior and edit/add guards."
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
