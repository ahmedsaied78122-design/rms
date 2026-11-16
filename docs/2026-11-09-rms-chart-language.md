# Chart color consistency and banner background — 2026-11-09

Chart colors previously classified translated series names using partial English/Arabic warning-word matches. Expense and Net Profit/Loss matched in English but their translated Arabic labels did not, yielding different colors for the same data. Color allocation now follows the existing series/category order in the fixed RMS palette, with no name-based classification. The first two series remain green and lime in both languages. Data, signs, chart type, callbacks and tooltip formatting remain unchanged; heatmap intensity colors are preserved.

Regression tests cover equivalent Arabic/English names and arbitrary renames across bar, line, pie, donut and percentage charts. A browser fixture using the actual installed chart library compared rendered SVG fills for Expense/Net Profit/Loss versus نفقة/صافي الربح / الخسارة and confirmed identical green/lime colors. No authenticated account or business data was changed.

A small local SVG adds a faint continuous marker line, restrained lavender marks and small accents behind the green hero contents. It connects the existing localized copy, approved artwork and tilted R without adding layout elements or changing the approved illustration. The overlay ignores pointer events, stays below live content and remains clipped to the hero. Existing bilingual banner checks passed again at 320, 390, 768, 1024 and 1600px. Desktop preview inspected.

Assets: studio JS `studio-9`, studio CSS `studio-14`; background `/assets/rms/images/rms-workspace-scribble-v1.svg`. Site cache cleared. Existing management workspace and shell unit suites passed.

Evidence: `/home/xxx/outputs/rms-chart-language/` and updated `/home/xxx/outputs/rms-approved-banner/`.
