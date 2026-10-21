const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const sourcePath = path.join(__dirname, "point_of_sale.js");
const source = `${fs.readFileSync(sourcePath, "utf8")}\nglobalThis.__RMSPointOfSale = RMSPointOfSale;`;

async function createHarness({ dialogValue, callbackValues, saved = true }) {
	let dialogConfig;
	const frappe = {
		pages: { "point-of-sale": {} },
		ui: { Dialog: class {
			constructor(config) { dialogConfig = config; this.$wrapper = { addClass() {} }; }
			show() {}
			hide() {}
			get_value(fieldname) { return fieldname === "notes" ? dialogValue : undefined; }
		} },
	};
	const context = vm.createContext({ frappe, __: (value) => value, document: {}, window: {}, setTimeout, clearTimeout });
	vm.runInContext(source, context, { filename: sourcePath });
	const pos = Object.create(context.__RMSPointOfSale.prototype);
	const row = { title: "Mint Lemonade", selling_product: "Mint Lemonade", notes: "", saved_to_order: saved, order_item_name: saved ? "ROW-1" : undefined };
	pos.state = { cart: [row], order_name: "ORDER-1", order_status: "Confirmed" };
	pos.flushDraftSave = async () => {};
	pos.renderCart = () => {};
	pos.showError = (error) => { throw error; };
	const calls = [];
	pos.call = async (method, args) => {
		calls.push({ method, args });
		if (method === "get_order") return { items: [{ name: "ROW-1", selling_product: "Mint Lemonade" }] };
		return { name: args.item_name, notes: args.notes };
	};
	pos.persistDraft = async () => { calls.push({ method: "save_order", notes: row.notes }); };
	pos.editItemNotes(0);
	await dialogConfig.primary_action(callbackValues);
	return { row, calls };
}

async function run() {
	assert.equal(source.includes("You can add items and confirm preparation"), false,
		"the order screen should not show an instructional handoff banner");
	assert.equal(source.includes('data-role="order-ownership"'), false,
		"the order screen should not render a handoff banner container");

	const { row, calls } = await createHarness({ dialogValue: "بدون ثلج", callbackValues: { notes: "" } });
	assert.equal(calls[0].method, "update_order_item_notes");
	assert.equal(calls[0].args.notes, "بدون ثلج", "save the value currently shown in the comment dialog");
	assert.equal(row.notes, "بدون ثلج");

	const recovered = await createHarness({ dialogValue: "قليل السكر", callbackValues: { notes: "" }, saved: false });
	assert.equal(recovered.row.order_item_name, "ROW-1", "recover the saved child row when the append response lacks its client mapping");
	assert.equal(recovered.calls.at(-1).args.notes, "قليل السكر");
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
