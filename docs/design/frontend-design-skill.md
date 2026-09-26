---
name: frontend-design
description: Create distinctive, production-grade frontend interfaces with high design quality. Use this skill when the user asks to build web components, pages, artifacts, posters, or applications (examples include websites, landing pages, dashboards, React components, HTML/CSS layouts, or when styling/beautifying any web UI). Generates creative, polished code and UI design that avoids generic AI aesthetics.
license: Complete terms in LICENSE.txt
---

## Project Design Direction: Executive Dashboard

**SELECTED AESTHETIC**: This project follows the **Executive Dashboard** design direction.

**Characteristics**:
- Refined serif (Cormorant Garamond) + geometric sans (Inter) typography pairing
- Light theme with sophisticated navy (#2c5282) and charcoal (#1a202c, #2d3748) palette
- Clean lines, generous whitespace, minimal border-radius (2px)
- Uppercase subtitles with letter-spacing for hierarchy
- Financial Times / Bloomberg editorial quality
- Professional boardroom sophistication
- Data-driven precision without being cold
- Timeless elegance that won't feel dated

**Color Palette**:
- Primary: Navy `#2c5282`
- Text: Charcoal `#1a202c`, `#2d3748`
- Secondary: Grays `#718096`, `#a0aec0`, `#cbd5e0`
- Backgrounds: White `#ffffff`, Light Gray `#f7fafc`
- Borders: `#e2e8f0`

**Typography**:
- Headings: Cormorant Garamond (serif) - removed from main pages, kept for special emphasis
- Body/UI: Inter (sans-serif)
- Navigation: Uppercase, letter-spacing 0.8px-1.5px

**Collapsible Sections (Dashboard Convention)**:
- Use text-only disclosure headers for collapsible panels (no boxed border chrome).
- Reuse shared collapse styles/classes rather than inline per-page button borders/backgrounds.
- Keep interaction affordance minimal: chevron + subtle text-color hover changes.

**Information Affordance & Hover-over Popovers (`(i)` Icons - Scheme A Convention)**:
- **Component**: Use `dbc.Popover` with `trigger="hover focus"` rather than unstyled `dbc.Tooltip`. The `focus` trigger keeps the help text reachable by keyboard/screen-reader users (tab onto the icon), matching the existing `scan_status.py` precedent.
- **Icon Styling**: Standardize on `html.I(className="fas fa-info-circle")` with `style={"cursor": "help", "marginLeft": "6px", "color": COLOR_GRAY_MEDIUM}`.
- **Inverted Contrast Scheme**:
  - In **Light Theme**: The popover renders an inverted dark card (`#1f262f` background, `#e6edf3` text, `#3a4653` border).
  - In **Dark Theme**: The popover renders an inverted light card (`#ffffff` background, `#1a202c` text, `#e2e8f0` border).
  - Apply the `popover-inverted` CSS class (or dynamic theme inversion) to achieve automatic high-contrast visibility.
- **Interaction & Content**:
  - Hover trigger keeps the popover active when the cursor moves onto the popover body, allowing comfortable reading and text selection.
  - Supports rich markdown formatting (`dcc.Markdown`) with clear typography and comfortable padding.

**Large Table Rendering (Performance Technique)**:
- **Problem**: Dash instantiates a component tree for every server callback output. For tables with many rows (e.g. 100+), this per-component instantiation dominates load time — a 140-row table can take ~10s to render even when the backend is fast.
- **Technique**: Render the table body in JavaScript, not as a Dash component tree. Use a `clientside_callback` that reads the raw data from a `dcc.Store` and builds the `<tr>`/`<td>` HTML directly in the browser (string concatenation + `innerHTML`). This bypasses Dash's component-instantiation cost entirely.
- **Skeleton-first**: Keep the table skeleton (header + empty `<tbody id="...">`) in the layout so the header renders instantly; the clientside callback fills the body.
- **Client-side filtering**: Keep search/filter in the same JS pass — no server round-trip, instant filtering.
- **Security**: Escape all user data in the JS (`&`, `<`, `>`, quotes) to avoid HTML injection.
- **Reference Implementation**: The Library page (`src/app/dash_app/pages/library/`) — `layout.py` renders the static skeleton; `callbacks.py` has the clientside callback that builds rows from `library-store`.
- **Trade-off**: Row-building logic moves to JS, so Python unit tests cover the data flow and skeleton rather than the rendered rows. Use this pattern for large, read-only, or frequently-filtered datasets; keep small tables as normal Dash components.

---

This skill guides creation of distinctive, production-grade frontend interfaces that avoid generic "AI slop" aesthetics. Implement real working code with exceptional attention to aesthetic details and creative choices.

The user provides frontend requirements: a component, page, application, or interface to build. They may include context about the purpose, audience, or technical constraints.

## Design Thinking

Before coding, understand the context and commit to a BOLD aesthetic direction:
- **Purpose**: What problem does this interface solve? Who uses it?
- **Tone**: Pick an extreme: brutally minimal, maximalist chaos, retro-futuristic, organic/natural, luxury/refined, playful/toy-like, editorial/magazine, brutalist/raw, art deco/geometric, soft/pastel, industrial/utilitarian, etc. There are so many flavors to choose from. Use these for inspiration but design one that is true to the aesthetic direction.
- **Constraints**: Technical requirements (framework, performance, accessibility).
- **Differentiation**: What makes this UNFORGETTABLE? What's the one thing someone will remember?

**CRITICAL**: Choose a clear conceptual direction and execute it with precision. Bold maximalism and refined minimalism both work - the key is intentionality, not intensity.

Then implement working code (HTML/CSS/JS, React, Vue, etc.) that is:
- Production-grade and functional
- Visually striking and memorable
- Cohesive with a clear aesthetic point-of-view
- Meticulously refined in every detail

## Frontend Aesthetics Guidelines

Focus on:
- **Typography**: Choose fonts that are beautiful, unique, and interesting. Avoid generic fonts like Arial and Inter; opt instead for distinctive choices that elevate the frontend's aesthetics; unexpected, characterful font choices. Pair a distinctive display font with a refined body font.
- **Color & Theme**: Commit to a cohesive aesthetic. Use CSS variables for consistency. Dominant colors with sharp accents outperform timid, evenly-distributed palettes.
- **Motion**: Use animations for effects and micro-interactions. Prioritize CSS-only solutions for HTML. Use Motion library for React when available. Focus on high-impact moments: one well-orchestrated page load with staggered reveals (animation-delay) creates more delight than scattered micro-interactions. Use scroll-triggering and hover states that surprise.
- **Spatial Composition**: tails**: Create atmosphere and depth rather than defaulting to solid colors. Add contextual effects and textures that match the overall aesthetic. Apply creative forms like gradient meshes, noise textures, geometric patterns, layered transparencies, dramatic shadows, decorative borders, custom cursors, and grain overlays.

NEVER use generic AI-generated aesthetics like overused font families (Inter, Roboto, Arial, system fonts), cliched color schemes (particularly purple gradients on white backgrounds), predictable layouts and component patterns, and cookie-cutter design that lacks context-specific character.

Interpret creatively and make unexpected choices that feel genuinely designed for the context. No design should be the same. Vary between light and dark themes, different fonts, different aesthetics. NEVER converge on common choices (Space Grotesk, for example) across generations.

**IMPORTANT**: Match implementation complexity to the aesthetic vision. Maximalist designs need elaborate code with extensive animations and effects. Minimalist or refined designs need restraint, precision, and careful attention to spacing, typography, and subtle details. Elegance comes from executing the vision well.

Remember: Claude is capable of extraordinary creative work. Don't hold back, show what can truly be created when thinking outside the box and committing fully to a distinctive vision.