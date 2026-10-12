"""Layout smoke tests for the Phase 2 catalog editor Test buttons + results modal."""

import pytest

from app.dash_app.pages.catalog.editor_layout import get_editor_layout


pytestmark = pytest.mark.unit


def _collect_ids() -> set[str]:
    """Every component id in the rendered editor layout (exact, unquoted)."""
    ids: set[str] = set()

    def walk(component) -> None:
        if component is None:
            return
        component_id = getattr(component, "id", None)
        if component_id is not None:
            ids.add(str(component_id))
        children = getattr(component, "children", None)
        if isinstance(children, (list, tuple)):
            for child in children:
                walk(child)
        elif children is not None:
            walk(children)

    walk(get_editor_layout())
    return ids


def test_quick_test_tabular_button_present():
    assert "editor-quick-test-tabular" in _collect_ids()


def test_quick_test_graph_button_present():
    assert "editor-quick-test-graph" in _collect_ids()


def test_view_test_tabular_button_present():
    assert "editor-view-test-tabular" in _collect_ids()


def test_view_test_graph_button_present():
    assert "editor-view-test-graph" in _collect_ids()


def test_inline_feedback_divs_present():
    ids = _collect_ids()
    assert "editor-quick-test-tabular-feedback" in ids
    assert "editor-quick-test-graph-feedback" in ids


def _collect_loading_child_ids() -> set[str]:
    """Every component id nested inside a dcc.Loading in the rendered layout."""
    from dash import dcc

    ids: set[str] = set()

    def walk(component, inside_loading: bool) -> None:
        if component is None:
            return
        in_loading = inside_loading or isinstance(component, dcc.Loading)
        component_id = getattr(component, "id", None)
        if in_loading and component_id is not None:
            ids.add(str(component_id))
        children = getattr(component, "children", None)
        if isinstance(children, (list, tuple)):
            for child in children:
                walk(child, in_loading)
        elif children is not None:
            walk(children, in_loading)

    walk(get_editor_layout(), False)
    return ids


def test_inline_feedback_divs_are_wrapped_in_loading():
    loading_ids = _collect_loading_child_ids()
    assert "editor-quick-test-tabular-feedback" in loading_ids
    assert "editor-quick-test-graph-feedback" in loading_ids


def test_test_modal_present():
    assert "editor-test-modal" in _collect_ids()


def test_old_test_results_div_gone():
    assert "editor-test-results" not in _collect_ids()


def test_test_fit_row_present():
    assert "editor-test-fit-row" in _collect_ids()


def _find_by_id(component, target_id):
    """Return the component with `target_id`, or None."""
    if component is None:
        return None
    if getattr(component, "id", None) == target_id:
        return component
    children = getattr(component, "children", None)
    if children is None:
        return None
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        found = _find_by_id(child, target_id)
        if found is not None:
            return found
    return None


def test_fit_row_has_no_display_utility_class():
    """Regression guard: the Fit row's visibility is toggled with an inline style,
    so it must not carry a Bootstrap display class — `.d-flex` etc. are declared
    `!important` in the loaded Bootswatch sheet (`.d-flex{display:flex!important}`)
    and would beat the inline `display: none`, leaving the button permanently
    visible on tabular results."""
    row = _find_by_id(get_editor_layout(), "editor-test-fit-row")
    assert row is not None, "editor-test-fit-row is missing from the modal"
    class_name = getattr(row, "className", None) or ""
    bad = [c for c in class_name.split() if c.startswith("d-")]
    assert not bad, f"Fit row carries a display utility class that defeats its inline style: {bad}"


def _style_output_ids() -> set[str]:
    """Ids that some callback writes a `style` prop to, excluding those whose display
    is managed through a `className` output instead (a display class is legitimate
    when the class itself is the thing being toggled)."""
    import app.dash_app.pages.catalog  # noqa: F401  (registers the callbacks)
    from dash import _callback

    def parse(sig: str) -> list[tuple[str, str]]:
        body = sig[2:] if sig.startswith("..") else sig
        body = body[:-2] if body.endswith("..") else body
        out = []
        for chunk in body.split("..."):
            if chunk:
                comp, _, prop = chunk.rpartition(".")
                out.append((comp, prop))
        return out

    style_ids: set[str] = set()
    class_ids: set[str] = set()
    for spec in _callback.GLOBAL_CALLBACK_LIST:
        for comp, prop in parse(spec["output"]):
            if prop == "style":
                style_ids.add(comp)
            elif prop == "className":
                class_ids.add(comp)
    return style_ids - class_ids


def _components_by_id(component, out: dict | None = None) -> dict:
    """Map every string id in the tree to its component."""
    if out is None:
        out = {}
    if component is None:
        return out
    component_id = getattr(component, "id", None)
    if isinstance(component_id, str):
        out[component_id] = component
    children = getattr(component, "children", None)
    if children is not None:
        for child in (children if isinstance(children, (list, tuple)) else [children]):
            _components_by_id(child, out)
    return out


def test_style_toggled_elements_carry_no_display_utility_class():
    """Invariant: when a callback controls an element's display via `style`, the
    element must NOT also carry a Bootstrap display utility class. Those are emitted
    `!important` in the loaded Bootswatch sheet (`.d-flex{display:flex!important}`),
    so they silently win and the style is ignored — which is exactly how the Fit row
    stayed visible through plan 026."""
    tree = _components_by_id(get_editor_layout())
    offenders = {}
    for component_id in sorted(_style_output_ids()):
        component = tree.get(component_id)
        if component is None:
            continue
        classes = (getattr(component, "className", None) or "").split()
        bad = [c for c in classes if c.startswith("d-")]
        if bad:
            offenders[component_id] = bad
    assert not offenders, (
        f"style-toggled elements carrying display utility classes: {offenders}"
    )


def test_fit_row_starts_hidden():
    """The row must be hidden at render time, not only once the results callback
    returns: plan 024 opens the modal before the fetch completes, so an unstyled row
    shows the Fit button for the whole request."""
    row = _find_by_id(get_editor_layout(), "editor-test-fit-row")
    assert row is not None, "editor-test-fit-row is missing from the modal"
    style = getattr(row, "style", None)
    assert isinstance(style, dict) and "display" in style, (
        f"fit row must set an explicit initial display, got {style!r}"
    )
    assert style["display"] == "none"
