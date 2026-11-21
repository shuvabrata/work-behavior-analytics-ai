# Executive Dashboard Design System

This document describes the centralized design system for the Work Behavior Analytics AI application's frontend. All design tokens, components, and styling patterns are defined in `src/ui/styles.py` and `src/ui/assets/executive-dashboard.css`.

## Table of Contents

1. [Design Philosophy](#design-philosophy)
2. [Theme Foundation](#theme-foundation)
3. [Color Palette](#color-palette)
4. [Typography](#typography)
5. [Spacing System](#spacing-system)
6. [Components](#components)
7. [CSS Variables](#css-variables)
8. [Usage Examples](#usage-examples)

---

## Design Philosophy

The Executive Dashboard aesthetic prioritizes:

- **Clarity**: Clean layouts with ample whitespace
- **Professionalism**: Refined typography using Cormorant Garamond (serif) and Inter (sans-serif)
- **Consistency**: Centralized design tokens prevent style drift
- **Accessibility**: Sufficient color contrast and readable font sizes
- **Restraint**: Navy accent color (#2c5282) used sparingly for emphasis

---

## Theme Foundation

The design system now has a semantic token layer in `src/ui/styles.py`.

- `THEME_TOKENS` stores theme values keyed by semantic names (for example `brand.primary`, `surface.base`, `text.muted`)
- `ACTIVE_THEME` defaults to `executive-dark`; it is the single source of truth for the default theme
- Supported themes: `executive-light`, `executive-dark`
- Existing exported constants (`COLOR_NAVY`, `COLOR_BORDER`, etc.) are still available and now resolve from semantic tokens
- Theme switching is persisted with `dcc.Store(storage_type="local")` and applied via `app-shell` theme classes (`theme-executive-light`, `theme-executive-dark`)
- CSS variables are defined for light mode under both `:root` and `:root[data-theme="executive-light"]`, with dark overrides in `.theme-executive-dark` in `src/ui/assets/executive-dashboard.css`

This preserves current visuals while making it easier to add future themes (for example `executive-dark`) without rewriting component code.

### Runtime Theme Toggle

- Theme is toggled by the top bar `theme-toggle-btn`
- Selection is persisted in `theme-store` (`localStorage`), so it is per-browser, not per-user
- The root container (`#app-shell`) receives `theme-{name}` class
- Graph node/edge Cytoscape stylesheet is rebuilt per theme for readable dark-mode graph rendering

---

## Color Palette

### Primary Colors

| Token | Value | Usage |
|-------|-------|-------|
| `COLOR_NAVY` | `#2c5282` | Primary accent (buttons, active states, headings) |
| `COLOR_NAVY_DARK` | `#1e3a5f` | Hover states for navy elements |
| `COLOR_NAVY_HOVER` | `#234164` | Alternative hover state |

### Text Colors

| Token | Value | Usage |
|-------|-------|-------|
| `COLOR_CHARCOAL` | `#1a202c` | Darkest text (headings) |
| `COLOR_CHARCOAL_MEDIUM` | `#2d3748` | Primary body text |
| `COLOR_GRAY_DARK` | `#4a5568` | Secondary text |
| `COLOR_GRAY_MEDIUM` | `#718096` | Tertiary text, labels |
| `COLOR_GRAY_LIGHT` | `#a0aec0` | Muted text, placeholders |
| `COLOR_GRAY_LIGHTER` | `#cbd5e0` | Borders, dividers, icons |

### Background Colors

| Token | Value | Usage |
|-------|-------|-------|
| `COLOR_BACKGROUND_WHITE` | `#ffffff` | Main backgrounds, cards |
| `COLOR_BACKGROUND_LIGHT` | `#f7fafc` | Alternate backgrounds, input fields |
| `COLOR_SURFACE_ACTIVE` | `#edf2f7` | Active navigation items |

### Border Colors

| Token | Value | Usage |
|-------|-------|-------|
| `COLOR_BORDER` | `#e2e8f0` | Standard borders |
| `COLOR_BORDER_LIGHT` | `#e2e8f0` | Light borders (same as standard) |

### Corner Radius

| Surface | Radius | Source |
|---------|--------|--------|
| Form controls (`.form-control`, `.form-select`, `textarea`, `.Select-control`, `.Select-menu-outer`) | 6px | `var(--bs-border-radius)` theme token |
| Buttons (`.btn`, `.btn-sm`, `.btn-lg`) | 6px | `var(--bs-border-radius)` via `--bs-btn-border-radius` |
| Chat message surfaces (user / assistant bubbles, inline cards) | 6px | inline `var(--bs-border-radius, 6px)` — `pages/chat.py` |
| Surfaces / containers / cards | 2px | `var(--border-radius, 2px)` |

**Enforcement.** The form-control radius is declared with `!important` so it can beat
Bootswatch Materia's hardcoded `.form-control { border-radius: 0 }`. Consequence: an
inline `borderRadius` on a `.form-control` / `.form-select` / `textarea` / react-select
control is silently ignored — set it in `assets/executive-dashboard.css`, not in a
component. Buttons work the opposite way: the button radius overrides Bootstrap's
`--bs-btn-border-radius` variable, which an inline `border-radius` *does* beat, so a
button carrying an inline radius keeps that value instead of 6px.

### Utility Colors

| Token | Value | Usage |
|-------|-------|-------|
| `COLOR_SUCCESS` | `#48bb78` | Success messages, positive indicators |
| `COLOR_WARNING` | `#ed8936` | Warning messages, caution indicators |
| `COLOR_ERROR` | `#f56565` | Error messages, critical alerts |
| `COLOR_INFO` | `#4299e1` | Informational messages |

---

## Typography

### Font Families

| Token | Value | Usage |
|-------|-------|-------|
| `FONT_SERIF` | `'Cormorant Garamond', serif` | Decorative elements (diamond icons, accents) |
| `FONT_SANS` | `'Inter', sans-serif` | All body text, UI elements |

**Google Fonts Import** (included in layout.py):
```
https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@300;400;600;700&family=Inter:wght@400;500;600;700&display=swap
```

### Font Sizes

| Token | Value | Usage |
|-------|-------|-------|
| `FONT_SIZE_XLARGE` | `42px` | Large decorative text |
| `FONT_SIZE_LARGE` | `16px` | Section headings |
| `FONT_SIZE_MEDIUM` | `15px` | Body text |
| `FONT_SIZE_SMALL` | `14px` | Small text, labels |
| `FONT_SIZE_XSMALL` | `13px` | Tiny text, captions |
| `FONT_SIZE_TINY` | `12px` | Helper text |
| `FONT_SIZE_XTINY` | `11px` | Footnotes, compact metadata |
| `FONT_SIZE_XXSMALL` | `11px` | Compact metadata |

`FONT_SIZE_XTINY` and `FONT_SIZE_XXSMALL` share the `11px` value as the floor of the scale; the names are kept separate because call sites import them individually.

### Font Weights

| Token | Value | Usage |
|-------|-------|-------|
| `FONT_WEIGHT_NORMAL` | `400` | Body text |
| `FONT_WEIGHT_MEDIUM` | `500` | Emphasized text |
| `FONT_WEIGHT_SEMIBOLD` | `600` | Headings, active states |
| `FONT_WEIGHT_BOLD` | `700` | Strong emphasis |

---

## Spacing System

Follows a consistent 4px/8px grid system:

| Token | Value | Usage |
|-------|-------|-------|
| `SPACING_XXXSMALL` | `4px` | Tight spacing |
| `SPACING_XXSMALL` | `8px` | Minimal spacing |
| `SPACING_XSMALL` | `12px` | Small spacing, margins |
| `SPACING_SMALL` | `16px` | Standard padding |
| `SPACING_MEDIUM` | `24px` | Section spacing |
| `SPACING_LARGE` | `32px` | Large gaps |
| `SPACING_XLARGE` | `40px` | Extra large gaps |
| `SPACING_XXLARGE` | `48px` | Maximum spacing |

**Design Rule**: Always use spacing tokens instead of hardcoded pixel values.

---

### Dense pages

The app carries two spacing tiers: the text scale is app-wide, density is per-page.

The **dense** pages are Graph, Timeline, Search, Catalog, and both Collaboration Network pages. These display lists and graphs, where space around content is worth more as content. The **card and form** pages — Analytics, Connectors, Settings, Developer, Chat — keep the roomier base spacing. Density is a property of the page, not of the app.

The mechanism is the `.dense-page` scope class, which a dense page puts on its root `html.Div`. Density rules in `executive-dashboard.css` are all scoped under `.dense-page`, so a card or form page cannot become dense.

The `SPACING_*` token values are the same on both tiers. Dense pages use page-local literal values; the tokens themselves are never changed, because they are shared with the card pages.

One exception recurs: an element whose size is set by an inline `style=` prop cannot be restyled by a stylesheet rule, since inline outranks any class selector. Density for such an element belongs in Python, not in the stylesheet.

---

## Components

### Page Headers

**Style Token**: `COMPACT_PAGE_HEADER_STYLE`

```python
from ui.components.common import create_page_header

# Usage — breadcrumb is a list of (label, href) segments; href=None = current page
header = create_page_header(
    [("Settings", "/app/settings"), ("Graph Styling", None)],
    "Customize graph colors, shapes, sizes, and node appearance.",
)
```

**Visual**: A single compact row — `BREADCRUMB | description` — above a full-width
bottom border. Uppercase breadcrumb with 0.8px letter spacing (per the Executive
Dashboard navigation rule).

**Color rules**:
- **Clickable breadcrumb segments** (`href` provided): navy (`COLOR_NAVY`), no underline
- **Current-page segment** (`href=None`): charcoal (`COLOR_CHARCOAL_MEDIUM`), non-clickable
- **Description** (after the `|` separator): gray (`COLOR_GRAY_MEDIUM`), sentence-case
- **`/`** separates breadcrumb segments; **`|`** separates the breadcrumb from the description

**Layout rule**: The header sits on the plain page background, **outside** any
`CARD_CONTAINER_STYLE` wrapper. The card container wraps only the page content
(cards, tables, etc.), never the header.

---

### Feature Cards

**Style Tokens**: `FEATURE_CARD_STYLE`, `FEATURE_CARD_TITLE_STYLE`, `FEATURE_CARD_DESCRIPTION_STYLE`

```python
from ui.components.common import create_feature_card

# Usage
card = create_feature_card(
    title="Feature Name",
    description="Description of the feature",
    icon="fas fa-chart-line"
)
```

**Visual**: Light gray background with navy left border accent

---

### Chat Messages

**Implementation**: Built inline in the chat page — see `render_messages` in `src/ui/pages/chat.py`. There are no chat-message style tokens.

**Visual**: 
- User messages: Navy background with white text, right-aligned
- Assistant messages: Light background with charcoal text, left-aligned

---

### Placeholder Sections

**Style Tokens**: `PLACEHOLDER_ICON_STYLE`, `PLACEHOLDER_MESSAGE_STYLE`

```python
from ui.components.common import create_placeholder_section

# Usage
placeholder = create_placeholder_section(
    icon="fas fa-inbox",
    message="No data available"
)
```

**Visual**: Centered gray icon with italic message text

---

### Navigation

**Style Tokens**: `SIDEBAR_STYLE`, `NAVBAR_BRAND_STYLE`, `TOPBAR_STYLE`, etc.

**CSS Classes**: `.executive-sidebar`, `.executive-nav-link`, `.executive-topbar`

**Visual**:
- Sidebar: White background, vertical nav links
- Nav links: Gray text, navy left border when active
- Topbar: White background with bottom border

---

### Account Menu

**Style Tokens**: `COLOR_CHARCOAL`, `COLOR_GRAY_MEDIUM`, `FONT_SANS`, `FONT_SIZE_SMALL`, `FONT_SIZE_XSMALL`, `FONT_WEIGHT_MEDIUM`

**CSS Classes**: `.account-menu`, `.account-menu-toggle`, `.account-menu-header`

**Visual**:
- Trigger: icon-only 32×32 button matching the theme toggle — transparent background, 1px `var(--color-border)` border, no caret
- Popup: right-aligned against the trigger; username in `COLOR_CHARCOAL`, full name beneath it in `COLOR_GRAY_MEDIUM` when the token supplies one
- Logout entry: menu-item styled submit control

---

### Graph Components

**Style Tokens**: `GRAPH_QUERY_TEXTAREA_STYLE`, `GRAPH_CYTOSCAPE_STYLE`, `GRAPH_HELPER_TEXT_STYLE`, etc.

**Visual**:
- Query console: Light gray background container
- Execute button: Navy button matching primary color
- Graph: White background with light gray border

---

### Destructive Buttons

**App Standard**: All delete/remove/destructive buttons MUST use `color="outline-danger"`.

```python
import dash_bootstrap_components as dbc

# Correct — red text/border, fills red on hover
delete_btn = dbc.Button(
    "Delete Configuration",
    id={"type": "connector-delete", "connector_type": connector_type},
    color="outline-danger",
    size="sm",
)

# Incorrect — solid red background
delete_btn = dbc.Button("Delete", color="danger")
```

**Visual**:
- Default: Red text and red border on a transparent/light background
- Hover: Fills red with white text
- Matches the "Reset All to Default" button on the Settings / Runtime page

**Confirmation Requirement**: Every destructive action MUST display a `dcc.ConfirmDialog` before executing. Use the 2-stage callback pattern:

1. **Stage 1** — button `n_clicks` sets `ConfirmDialog.displayed = True`
2. **Stage 2** — dialog `submit_n_clicks` performs the actual destructive operation

```python
from dash import dcc

# In layout
dcc.ConfirmDialog(
    id="connector-delete-confirm",
    message="Are you sure you want to delete ALL configurations "
            "for this connector? This cannot be undone.",
)

# Stage 1: show the dialog
@callback(
    Output("connector-delete-confirm", "displayed"),
    Input({"type": "connector-delete", "connector_type": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def confirm_connector_delete(_clicks):
    if not any(n for n in _clicks if n):
        raise PreventUpdate
    return True

# Stage 2: perform the delete on submit
@callback(
    Output(..., allow_duplicate=True),
    Input("connector-delete-confirm", "submit_n_clicks"),
    prevent_initial_call=True,
)
def perform_connector_delete(submit_clicks):
    if not submit_clicks:
        raise PreventUpdate
    # ... perform the destructive operation
```

The dialog message must state the scope of destruction and include the phrase "This cannot be undone."

---

### Neutral / Secondary Buttons

**App Standard**: The app MUST NOT rely on Bootstrap's stock `secondary` variant (`.btn-outline-secondary`). The theme CSS does not restyle that variant, and its `#6c757d` text fails contrast against both theme backgrounds. Pair `color="secondary", outline=True` with `className="btn-subtle-action"`, which supplies theme-aware tokens instead.

```python
import dash_bootstrap_components as dbc

compare_btn = dbc.Button(
    "Compare to Factory",
    id="editor-view-changes",
    color="secondary",
    outline=True,
    className="btn-subtle-action",
    size="sm",
)
```

---

### Form Inputs & Dropdowns

**App Standard**: Use `dbc.Select` (native `<select>`, styled via Bootstrap's `.form-select`) for every single-choice dropdown. One control for the whole app is what keeps filter bars and form rows visually identical across pages; `dcc.Dropdown` is a separate component with its own markup, sizing and behaviour, so mixing the two produces controls that disagree on height, padding and focus treatment.

```python
import dash_bootstrap_components as dbc

# Correct — native <select>, one control app-wide
picker = dbc.Select(
    id="catalog-namespace-filter",
    options=[{"label": "All namespaces", "value": "__all__"}],
    value="__all__",
    size="sm",
)

# Incorrect — a second dropdown component that will not match dbc.Select
from dash import dcc
picker = dcc.Dropdown(
    id="my-dropdown",
    options=[{"label": "A", "value": "a"}],
)
```

Do not set height, border, font or padding inline. `.form-select` in `executive-dashboard.css` already owns background, border, radius, focus ring and font weight in both themes, and an inline override shadows those rules rather than extending them. Pass only a width when a layout slot needs one — width is the one property the stylesheet cannot know.

**Sizing**: use `size="sm"` for selectors inside cards, toolbars and filter rows. Use the default size only for a primary form control in a full-width form.

**Native `<select>` cannot hold a null value.** To express an "inherit default / no selection" state, add an explicit first option with an empty value and treat `""` as unset in callbacks:

```python
options = [{"label": "Inherit (default)", "value": ""}] + [
    {"label": shape, "value": shape} for shape in ALLOWED_SHAPES
]
```

A filter sentinel such as `__all__` ("All namespaces") is **not** this case — it is a real, selectable third state meaning "do not filter", and callbacks test for it by name. Reserve `""` for "unset"; reserve a named sentinel for "all".

**Multi-select fields use `dbc.Checklist`, not a dropdown.** A multi-select cannot be a native `<select>` without the `multiple` attribute, and `dcc.Dropdown`'s `multi=True` is the one thing the `dbc.Select` standard cannot cover — so multi-select is a separate idiom rather than an exception to it. `dbc.Checklist` renders one checkbox per option, inherits the themed `.form-check-input` rules, and its value is already a list, which is the shape the connector config read-back path expects. Connector forms declare this as `input_type: FIELD_MULTISELECT`.

**Visual**:
- Light theme: white background, charcoal text, navy focus ring
- Dark theme: dark surface (`--color-background-light`), light text — no white backgrounds
- Reference implementation: Graph page → Right panel → Catalog tab → Namespace picker (`dbc.Select`)

---

All CSS variables are defined in `src/ui/assets/executive-dashboard.css`:

```css
:root,
:root[data-theme="executive-light"] {
    /* Colors */
    --color-navy: #2c5282;
    --color-charcoal-medium: #2d3748;
    --color-background-light: #f7fafc;
    
    /* Typography */
    --font-sans: 'Inter', sans-serif;
    --font-size-small: 14px;
    --font-size-xsmall: 13px;
    
    /* Spacing */
    --spacing-xxsmall: 8px;
    --spacing-xsmall: 12px;
    --spacing-medium: 24px;
    
    /* Transitions */
    --transition-base: 0.2s ease;
}
```

**Usage in custom CSS**:

```css
.my-custom-class {
    color: var(--color-navy);
    font-family: var(--font-sans);
    padding: var(--spacing-small);
}
```

---

## Usage Examples

### Creating a New Page

```python
from dash import html
import dash_bootstrap_components as dbc
from ui.components.common import create_page_header, create_feature_card
from ui.styles import CARD_CONTAINER_STYLE

def get_layout():
    return html.Div([
        # Page header — sits on the plain background, OUTSIDE the card container
        create_page_header(
            [("My New Page", None)],
            "A short description of what this page does.",
        ),

        # Card container — wraps only the page content, never the header
        html.Div([
            create_feature_card(
                title="Feature 1",
                description="Description here",
                icon="fas fa-rocket"
            ),
            create_feature_card(
                title="Feature 2",
                description="Another description",
                icon="fas fa-chart-bar"
            )
        ], style=CARD_CONTAINER_STYLE)
    ])
```

---

### Using Design Tokens Directly

```python
from dash import html
from ui.styles import (
    COLOR_NAVY,
    FONT_SANS,
    SPACING_MEDIUM,
    SPACING_SMALL
)

custom_div = html.Div(
    "Custom Content",
    style={
        "color": COLOR_NAVY,
        "fontFamily": FONT_SANS,
        "padding": f"{SPACING_SMALL} {SPACING_MEDIUM}",
        "borderRadius": "2px"
    }
)
```

---

### Merging Styles

```python
from ui.styles import FEATURE_CARD_STYLE, merge_styles

custom_card_style = merge_styles(
    FEATURE_CARD_STYLE,
    {"boxShadow": "0 4px 6px rgba(0,0,0,0.1)"}
)

card = html.Div("Content", style=custom_card_style)
```

---

### Custom CSS with Variables

```css
/* In executive-dashboard.css or custom stylesheet */

.my-page-specific-class {
    background-color: var(--color-background-light);
    border: 1px solid var(--color-border);
    padding: var(--spacing-medium);
    font-family: var(--font-sans);
    font-size: var(--font-size-small);
    color: var(--color-charcoal-medium);
    transition: all var(--transition-base);
}

.my-page-specific-class:hover {
    background-color: var(--color-surface-active);
    border-color: var(--color-navy);
}
```

---

## Best Practices

1. **Always use design tokens**: Never hardcode colors, fonts, or spacing values
2. **Use semantic theme tokens for new work**: Add/update values in `THEME_TOKENS` first, then map to exported constants if needed
3. **Use helper components**: Prefer `create_page_header()` over custom implementations
4. **Keep CSS minimal**: Use Python style dictionaries for most styling
5. **Use CSS for interactions**: Hover states, animations, and transitions belong in CSS
6. **Maintain consistency**: If a pattern exists, reuse it instead of creating variations
7. **Test visual regression**: Verify no visual changes when refactoring styles

---

## Maintenance

### Adding New Colors

1. Add constant to `src/ui/styles.py`:
   ```python
   COLOR_NEW = "#hexcode"
   ```

2. Add CSS variable to `src/ui/assets/executive-dashboard.css`:
   ```css
   :root {
       --color-new: #hexcode;
   }
   ```

### Adding New Components

1. Add component function to `src/ui/components/common.py`
2. Add style constants to `src/ui/styles.py`
3. Document in this file under "Components" section
4. Add usage example

### Updating Existing Styles

1. Change the constant value in `styles.py`
2. Update corresponding CSS variable if applicable
3. Verify all pages still look correct
4. Run linting to ensure no errors

---

## File Structure

```
src/ui/                             # Imported as the top-level `ui` package
├── layout.py                       # App shell, nav, and route → page dispatch
├── styles.py                       # Python design tokens (single source of truth)
├── api_client.py                   # HTTP client to the backend API
├── settings.py                     # UISettings (credential-free)
├── runtime_settings.py             # Runtime-settings snapshot from the API
├── auth.py                         # BFF session handling
├── session_guard.py                # Session-expiry guard
├── stream_proxy.py                 # Chat streaming proxy
├── request_logging.py              # Request logging
├── graph_styles.py                 # Shared graph styling used across pages
├── collaboration_params.py         # Shared collaboration-network parameters
├── components/                     # Shared UI components
│   ├── common.py                   # Page headers, feature cards, placeholder sections
│   ├── account_bar.py              # Account menu
│   ├── hub_card.py                 # Hub card
│   ├── permission_errors.py        # Permission-error surfaces
│   ├── person_picker.py            # Person picker
│   ├── result_pane.py              # Shared result pane
│   ├── setup_banner.py             # Setup banner
│   └── spotlight.py                # Spotlight
├── assets/                         # Served CSS and JavaScript
│   ├── executive-dashboard.css     # CSS animations, interactions, variables
│   ├── sidebar.css                 # Sidebar styles
│   ├── stream-bridge.js            # Chat streaming bridge
│   └── tooltip-transform.js        # Graph tooltip positioning
└── pages/
    ├── analytics.py                # Analytics page (single module)
    ├── chat.py                     # Chat page (single module)
    ├── search.py                   # Search page (single module)
    ├── catalog/                    # Page package: layout.py + callbacks.py
    ├── collaboration_network/      # Page package: layout.py + callbacks/
    ├── collaboration_network_ego/  # Page package: layout.py + callbacks/
    ├── connectors/                 # Page package: layout.py + callbacks.py
    ├── developer/                  # Page package: layout.py + callbacks.py
    ├── graph/                      # Page package: layout.py + callbacks/
    ├── settings/                   # Page package: layout.py + callbacks.py
    └── timeline/                   # Page package: layout.py + callbacks.py
```

A page is either a single module (`analytics.py`, `chat.py`, `search.py`) or a package
directory whose `__init__.py` imports its `callbacks` module, so the page's callbacks
register on import.

---

## Version History

- **v1.0** (Current): Initial design system implementation
  - Centralized all design tokens in `styles.py`
  - Created reusable components in `common.py`
  - Converted CSS to use variables
  - Refactored all pages to use design system
