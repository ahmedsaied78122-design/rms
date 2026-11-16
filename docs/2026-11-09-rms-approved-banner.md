# Approved RMS street-art banner — 2026-11-09

The user approved the scattered ivory R, mint M and lime dollar-sign composition, with the checkerboard scrap removed. The existing tilted HTML R badge and live localized greeting remain. The decorative artwork occupies a separate grid column on larger screens and a compact second row on phones; it never overlaps the greeting or badge. RTL changes column order without mirroring the artistic letterforms.

Final project asset: `rms/public/images/rms-workspace-street-art-v1.webp` (1774×887, transparent alpha, approximately 331 KiB). A built-in image generation edit extracted the approved central art with transparency. The selected output was encoded as WebP with alpha preserved; no drawing modifications were made during encoding. The source generated PNG remains in the default generated-images location. The previous SVG remains in the repository but is no longer referenced by this hero.

## Final asset prompt (built-in image generation)

Asset extraction / background removal from this approved banner, NOT a redesign. Extract ONLY the central street-art composition into a genuinely transparent-background PNG: the large ivory brush R on left, mint collage M lower center, lime brush dollar sign $ upper right, small ivory four-point sparkle, thin ivory loop, purple/lavender tape and restrained ivory/lime spray dots. Preserve the exact approved artwork shapes, style, colors and relative positions. Exclude ALL banner UI: no dark green rectangle/background, no ivory surround, no RMS / MANAGEMENT, no headline/subtitle, no far-right tilted lime R badge. Only central R M $ collage art with transparent space behind/around it, including transparent gaps inside letters, and clean natural paint edges. No checkerboard/racing scrap. Do not add or change any element or add a drop shadow. Tight landscape art bounding box with small transparent safety margins, full artwork visible and no clipping. This transparent art will be placed between live HTML greeting text and a separate existing HTML R badge.

## Verification

- Native workspace ownership/save unit checks passed.
- Existing isolated browser workspace and shortcut checks passed again.
- The real asset decoded in browser fixtures. English/Arabic headings, image containment, absence of text/badge overlap, non-mirrored letters and visible tilted R were checked at 320, 390, 768, 1024 and 1600px. Screenshots were inspected for desktop English and phone Arabic.
- All fixture data and saves were isolated; no authenticated user, business record or workspace content was changed for testing.
- Final versions: studio JS `studio-8`, studio CSS `studio-13`. Site cache cleared. Public asset availability checked with an unauthenticated browser.

Evidence: `/home/xxx/outputs/rms-approved-banner/`.
