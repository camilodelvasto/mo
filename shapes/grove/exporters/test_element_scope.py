from element_scope import scope_token, scope_css


def test_scope_token_is_deterministic():
    assert scope_token("hero", "body-css") == scope_token("hero", "body-css")
    assert scope_token("hero", "a") != scope_token("hero", "b")


def test_simple_selector_gets_attribute():
    out = scope_css(".hero h1 { color: red; }", "p-abcd")
    assert '[data-p-abcd]' in out
    assert ".hero" in out and "h1" in out


def test_comma_selectors_each_scoped():
    out = scope_css("h1, h2 { margin: 0; }", "p-abcd")
    assert out.count("[data-p-abcd]") == 2


def test_media_query_inner_rules_scoped():
    out = scope_css("@media (min-width: 600px) { .x { color: red; } }", "p-abcd")
    assert "@media" in out
    assert "[data-p-abcd]" in out


def test_keyframes_not_scoped():
    out = scope_css("@keyframes spin { from { opacity: 0; } to { opacity: 1; } }", "p-abcd")
    assert "[data-p-abcd]" not in out
    assert "@keyframes" in out


# --- regression tests for correctness fixes ---

def test_root_not_prefixed():
    out = scope_css(":root { --brand: red; }", "p-abcd")
    assert ":root" in out
    # must not inject [data-...] before :root
    assert "[data-p-abcd] :root" not in out
    assert "[data-" not in out.split(":root")[0]


def test_body_not_prefixed():
    out = scope_css("body { margin: 0; }", "p-abcd")
    assert "body" in out
    assert "[data-p-abcd]" not in out


def test_html_not_prefixed():
    out = scope_css("html { box-sizing: border-box; }", "p-abcd")
    assert "html" in out
    assert "[data-p-abcd]" not in out


def test_is_pseudo_scoped_once_no_inner_injection():
    out = scope_css(":is(h1, h2) { margin: 0; }", "p-abcd")
    # exactly one scope attribute prefix
    assert out.count("[data-p-abcd]") == 1
    # the :is( group must be intact — no [data- injected inside the parens
    assert ":is(h1, h2)" in out or ":is(h1,h2)" in out
    # confirm no [data- appears inside the parens
    is_block_start = out.index(":is(")
    is_block_end = out.index(")", is_block_start)
    assert "[data-" not in out[is_block_start:is_block_end]


def test_attribute_selector_with_comma_in_value():
    out = scope_css('[data-x="a,b"] { color: red; }', "p-abcd")
    # the "a,b" value must survive intact
    assert '"a,b"' in out


def test_output_does_not_start_with_space():
    out = scope_css(".hero { color: red; }", "p-abcd")
    assert out == out.lstrip(), f"output starts with whitespace: {out!r}"
