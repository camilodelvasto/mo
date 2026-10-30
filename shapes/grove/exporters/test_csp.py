from csp import compute_csp


def _grove():
    return {"features": [{"id": "chatbotX", "type": "chat", "ask": "faq"}]}


def _endpoints():
    return {"chatbotX": "https://ask.example.com"}


def test_default_is_locked_down():
    page = {"body": ["header", "footer"]}
    csp = compute_csp(page, _grove(), feature_endpoints={})
    assert "default-src 'self'" in csp
    assert "connect-src 'none'" in csp
    assert "form-action 'none'" in csp
    assert "frame-src 'none'" in csp


def test_body_feature_grants_connect_src():
    page = {"body": ["header", {"feature": "chatbotX"}, "footer"]}
    csp = compute_csp(page, _grove(), feature_endpoints=_endpoints())
    assert "connect-src https://ask.example.com" in csp
    assert "connect-src 'none'" not in csp


def test_ambient_feature_in_egress_grants_connect_src():
    page = {"body": ["header", "footer"],
            "egress": {"features": ["chatbotX"]}}
    csp = compute_csp(page, _grove(), feature_endpoints=_endpoints())
    assert "connect-src https://ask.example.com" in csp


def test_missing_endpoint_raises():
    """No fallback: a feature used on a page with no resolved endpoint must raise."""
    page = {"body": ["header", {"feature": "chatbotX"}, "footer"]}
    try:
        compute_csp(page, _grove(), feature_endpoints={})
        assert False, "expected KeyError"
    except KeyError as e:
        assert "chatbotX" in str(e)


def test_form_endpoint_widens_form_action_and_connect():
    page = {
        "body": ["header", "footer"],
        "egress": {
            "forms": [{"endpoint": "https://forms.example.com/submit"}],
        },
    }
    csp = compute_csp(page, _grove(), feature_endpoints={})
    assert "form-action https://forms.example.com/submit" in csp
    assert "connect-src https://forms.example.com/submit" in csp


def test_embed_origin_widens_frame_src():
    page = {
        "body": ["header", "footer"],
        "egress": {
            "embeds": [{"origin": "https://embed.example.com"}],
        },
    }
    csp = compute_csp(page, _grove(), feature_endpoints={})
    assert "frame-src https://embed.example.com" in csp


def test_connect_dedupes_form_endpoint_matching_feature_origin():
    """If a form endpoint equals a feature's origin, connect-src should list it once."""
    page = {
        "body": ["header", {"feature": "chatbotX"}, "footer"],
        "egress": {
            "forms": [{"endpoint": "https://ask.example.com"}],
        },
    }
    csp = compute_csp(page, _grove(), feature_endpoints=_endpoints())
    # connect-src must not list the origin twice
    connect_directive = [d for d in csp.split("; ") if d.startswith("connect-src")][0]
    origins = connect_directive[len("connect-src "):].split()
    assert origins.count("https://ask.example.com") == 1


# --- injection / dedup regression tests ---


def test_feature_endpoint_with_semicolon_raises():
    """A feature endpoint containing ';' must raise ValueError (CSP injection guard)."""
    page = {
        "body": ["header", {"feature": "chatbotX"}, "footer"],
    }
    try:
        compute_csp(
            page,
            _grove(),
            feature_endpoints={"chatbotX": "https://x; script-src *"},
        )
        assert False, "expected ValueError"
    except ValueError as e:
        assert "unsafe CSP source" in str(e)


def test_form_endpoint_with_space_raises():
    """A form endpoint containing whitespace must raise ValueError."""
    page = {
        "body": ["header", "footer"],
        "egress": {
            "forms": [{"endpoint": "https://bad example.com/submit"}],
        },
    }
    try:
        compute_csp(page, _grove(), feature_endpoints={})
        assert False, "expected ValueError"
    except ValueError as e:
        assert "unsafe CSP source" in str(e)


def test_duplicate_embed_origins_appear_once_in_frame_src():
    """Two embeds with the same origin must produce a single frame-src entry."""
    page = {
        "body": ["header", "footer"],
        "egress": {
            "embeds": [
                {"origin": "https://e.com"},
                {"origin": "https://e.com"},
            ],
        },
    }
    csp = compute_csp(page, _grove(), feature_endpoints={})
    frame_directive = [d for d in csp.split("; ") if d.startswith("frame-src")][0]
    origins = frame_directive[len("frame-src "):].split()
    assert origins.count("https://e.com") == 1


def test_duplicate_form_endpoints_appear_once_in_form_action():
    """Two forms with the same endpoint must produce a single form-action entry."""
    page = {
        "body": ["header", "footer"],
        "egress": {
            "forms": [
                {"endpoint": "https://forms.example.com/submit"},
                {"endpoint": "https://forms.example.com/submit"},
            ],
        },
    }
    csp = compute_csp(page, _grove(), feature_endpoints={})
    form_directive = [d for d in csp.split("; ") if d.startswith("form-action")][0]
    endpoints = form_directive[len("form-action "):].split()
    assert endpoints.count("https://forms.example.com/submit") == 1


def test_script_hash_widens_script_src():
    page = {"body": ["footer"]}
    csp = compute_csp(page, _grove(), feature_endpoints={}, script_hashes=["sha256-abc"])
    assert "script-src 'self' 'sha256-abc'" in csp
