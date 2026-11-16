const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const context = {
	frappe: { pages: { "point-of-sale": {} }, msgprint(message) { context.messages.push(message); } },
	messages: [],
	clearTimeout,
	__: (text, args = []) => text.replace(/\{(\d+)\}/g, (_, index) => args[index]),
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, "point_of_sale.js"), "utf8") +
	"\nglobalThis.POS = RMSPointOfSale;", context);

function createPOS() {
	const pos = Object.create(context.POS.prototype);
	pos.state = {
		store: "Maadi", brand: "Bayt Al Sharq", order_type: "Takeaway", session: null,
		stores: [], brands: [], order_types: [], categories: [], products: [], cart: [],
		permissions: { can_checkout: true }, catalog_mode: "products", search: "", bootstrap_loading: false,
	};
	pos.catalogRequestId = 0;
	pos.output = {};
	pos.page = { main: { find(selector) {
		const field = pos.output[selector] ||= {};
		const node = {
			html(value) { field.html = value; return node; },
			text(value) { field.text = value; return node; },
			prop(key, value) { field[key] = value; return node; },
			each() { return node; },
			toggle() { return node; },
		};
		return node;
	} } };
	pos.escape = value => String(value ?? "");
	pos.currency = value => `${value} EGP`;
	pos.showError = error => { throw error; };
	return pos;
}

async function run() {
	const pos = createPOS();
	pos.call = async (method, args) => {
		assert.equal(method, "get_catalog", "browsing must only request catalog data");
		assert.equal(args.search, "كشري");
		return [{ name: "كشري مصري", title: "كشري مصري", image: "/files/koshari.jpg", price: 65 }];
	};
	pos.state.search = "كشري";
	await pos.loadCatalog();
	assert.match(pos.output['[data-role="products"]'].html, /كشري مصري/);
	assert.match(pos.output['[data-role="products"]'].html, /65 EGP/);
	assert.match(pos.output['[data-role="products"]'].html, /koshari\.jpg/);
	assert.equal(pos.output['[data-role="catalog-count"]'].text, "1 products");
	assert.equal(pos.state.session, null);

	// Only parentless categories belong in the top row; nested levels use the rail.
	const tree = createPOS();
	tree.state.categories = [
		{name: "Drinks", title: "Drinks"},
		{name: "Hot", title: "Hot drinks", parent_product_category: "Drinks", image: "/files/hot.jpg"},
		{name: "Cold", title: "Cold drinks", parent_product_category: "Drinks"},
		{name: "Coffee", title: "Coffee", parent_product_category: "Hot"},
		{name: "Tea", title: "Tea", parent_product_category: "Hot"},
		{name: "Food", title: "Food"},
	];
	tree.state.products = [
		{name: "Matcha", title: "Matcha", product_category: "Drinks", price: 80},
		{name: "Latte", title: "Latte", product_category: "Hot", price: 70},
		{name: "Espresso", title: "Espresso", product_category: "Coffee", price: 60},
		{name: "Rice", title: "Rice", product_category: "Food", price: 50},
	];
	tree.state.catalog_mode = "categories";
	tree.renderCategories(); tree.renderProducts();
	let markup = tree.output['[data-role="products"]'].html;
	assert.match(markup, /data-category="Drinks"/);
	assert.doesNotMatch(markup, /data-category="Hot"|data-category="Coffee"|data-product=/);
	assert.doesNotMatch(tree.output['[data-role="categories"]'].html, /data-category="Hot"|data-category="Cold"|data-category="Coffee"/);
	assert.equal(tree.output['[data-role="subcategories"]'].hidden, true);
	tree.state.category = "Drinks";
	tree.categoryNavOpen = true;
	tree.renderCategories(); tree.renderProducts();
	markup = tree.output['[data-role="products"]'].html;
	let rail = tree.output['[data-role="subcategories"]'].html;
	assert.equal(tree.output['[data-role="subcategories"]'].hidden, true, 'main categories use the full-width card grid without a duplicate side list');
	assert.equal(rail, '');
	assert.equal(tree.categoryNavOpen, false, 'returning to the first level closes the mobile panel');
	assert.doesNotMatch(tree.output['[data-role="category-context"]'].html, /data-category-nav-toggle/);
	assert.match(markup, /data-product="Matcha"/);
	assert.match(markup, /data-category="Hot"/);
	assert.match(markup, /hot\.jpg/);
	assert.doesNotMatch(markup, /data-category="Coffee"|data-product="Latte"|data-product="Espresso"|data-product="Rice"/);
	assert.match(tree.output['[data-role="categories"]'].html, /class="is-active" data-category="Drinks"/);
	tree.state.category = "Hot"; tree.renderCategories(); tree.renderProducts();
	rail = tree.output['[data-role="subcategories"]'].html;
	assert.match(rail, /data-category="Coffee"/);
	assert.match(rail, /data-category-back="Drinks"/);
	assert.doesNotMatch(rail, /data-category="Cold"/);
	assert.doesNotMatch(tree.output['[data-role="products"]'].html, /data-product="Matcha"/);
	assert.match(tree.output['[data-role="products"]'].html, /data-category="Coffee"/);
	assert.match(tree.output['[data-role="products"]'].html, /data-product="Latte"/);
	assert.doesNotMatch(tree.output['[data-role="products"]'].html, /data-product="Espresso"/);
	assert.match(tree.output['[data-role="category-context"]'].html, /data-category="Drinks"/);
	tree.state.category = "Coffee"; tree.renderCategories(); tree.renderProducts();
	rail = tree.output['[data-role="subcategories"]'].html;
	assert.match(rail, /data-category="Coffee" class="is-active" aria-current="page"/);
	assert.match(rail, /data-category="Tea"/);
	assert.match(rail, /data-category-back="Hot"/);
	assert.doesNotMatch(tree.output['[data-role="products"]'].html, /data-product="Latte"/);
	assert.match(tree.output['[data-role="products"]'].html, /data-product="Espresso"/);
	// Browsing and moving back are read-only and must not await an order-state check.
	tree.ensureCurrentOrderActive = () => { throw Error('Unexpected order-state check'); };
	tree.call = async (method, args) => { assert.equal(method, "get_catalog");assert.equal(args.include_descendants, 1);assert.equal(args.full_menu, 1);assert.equal(args.category, null); return []; };
	tree.state.search = 'old search';
	await tree.selectCategory('Hot');
	assert.equal(tree.state.search, '');assert.equal(tree.state.category, 'Hot');
	assert.match(tree.output['[data-role="subcategories"]'].html, /data-category="Tea"/);
	await tree.loadCatalog();
	tree.state.search = "Latte";
	tree.call = async (method, args) => { assert.equal(args.include_descendants, 1); return [{name:"Latte", title:"Latte", product_category:"Hot", price:70}]; };
	await tree.loadCatalog();
	assert.match(tree.output['[data-role="products"]'].html, /data-product="Latte"/);
	assert.doesNotMatch(tree.output['[data-role="products"]'].html, /data-category-card/);
	tree.call = async () => [];
	await tree.selectCategory('Drinks');
	assert.equal(tree.output['[data-role="subcategories"]'].hidden, true, 'parent navigation restores the card-only first level');
	assert.match(tree.output['[data-role="products"]'].html, /data-category="Hot"/);
	// A menu assigned to a child without its parent still has a browsable root.
	tree.state.categories = [{name:"Cold", title:"Cold", parent_product_category:"Unavailable"}];
	tree.state.category = null;
	assert.equal(tree.categoryLevel().children[0].name, "Cold");
	tree.renderCategories();
	assert.doesNotMatch(tree.output['[data-role="categories"]'].html, /data-category="Cold"/, 'a missing parent must not turn a child into a top-level category');
	// Defensive traversal terminates even if old category data has a cycle.
	tree.state.categories = [{name:'A',parent_product_category:'B'}, {name:'B',parent_product_category:'A'}];
	tree.state.category = 'A';
	assert.equal(tree.categoryLevel().path.length, 2);assert.equal(tree.categoryLevel().descendants.size, 2);

	// Rendering must enable catalog search before a session exists.
	for (const method of ["updateOrderTypeFields", "renderFields", "renderCategories", "renderCart"]) pos[method] = () => {};
	pos.render();
	assert.equal(pos.output['[data-search]'].disabled, false);
	assert.equal(pos.output['[data-action="scan"]'].disabled, false);
	await pos.addProduct("كشري مصري");
	assert.match(context.messages.at(-1), /Open a cashier session/);
	assert.equal(pos.state.cart.length, 0, "browsing must not bypass the sale session requirement");

	// Initial page bootstrap should load the default branch menu without a session.
	const initial = createPOS();
	initial.call = async () => ({
		stores: [{ name: "Maadi" }], store: { name: "Maadi" },
		brands: [{ name: "Bayt Al Sharq", is_default: true }],
		order_types: [{ name: "Takeaway" }], session: null,
	});
	initial.render = initial.loadContextDetails = initial.applyLaunchContext = () => {};
	let catalogLoads = 0;
	initial.loadCatalog = async () => { catalogLoads++; };
	await initial.loadBootstrap("Maadi");
	assert.equal(catalogLoads, 1);
	assert.equal(initial.state.bootstrap_loading, false);

	// Clearing the context must discard a pending response from the previous branch.
	const changing = createPOS();
	let finishRequest;
	changing.call = () => new Promise(resolve => { finishRequest = resolve; });
	const oldRequest = changing.loadCatalog();
	changing.state.store = null;
	await changing.loadCatalog();
	finishRequest([{ name: "Old branch product" }]);
	await oldRequest;
	assert.equal(changing.state.products.length, 0);
	assert.doesNotMatch(changing.output['[data-role="products"]'].html, /Old branch product/);
	assert.match(changing.output['[data-role="products"]'].html, /Select a Store/);
	// Rapid drill-down must not let a slower response restore a previous branch.
	const racing = createPOS(); let finishMenu, menuCalls = 0;
	racing.state.categories = [{name:'Root'}, {name:'A',parent_product_category:'Root'}, {name:'B',parent_product_category:'Root'}];
	racing.call = (method,args) => {menuCalls++;return new Promise(resolve => {finishMenu = resolve;});};
	const older = racing.selectCategory('A');const newer = racing.selectCategory('B');
	assert.equal(menuCalls, 1, 'rapid category changes share one full-menu request');
	finishMenu([{name:'Current',title:'Current',product_category:'B',price:25}, {name:'Stale',title:'Stale',product_category:'A',price:25}]);
	await newer;await older;
	assert.equal(racing.state.category, 'B');
	assert.match(racing.output['[data-role="products"]'].html, /data-product="Current"/);
	assert.doesNotMatch(racing.output['[data-role="products"]'].html, /data-product="Stale"/);
	console.log("PASS: menu loads and renders without a session; search works; sales remain protected; stale menus are discarded.");
}

run().catch(error => { console.error(error); process.exitCode = 1; });
