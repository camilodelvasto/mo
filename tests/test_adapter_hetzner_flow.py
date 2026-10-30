# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""The box flow against a fake box: in-memory files, symlinks and release dirs,
plus the ordered list of operations. Asserts ORDER and REFUSALS; command SHAPE
only where the shape is the safety property (relative flip, .part upload,
hex-only prune under the lock, validate before DNS). The fake is strict: a
command it does not model fails the test."""
import json
import re
import pytest
from shapes.shared.adapters import hetzner
from shapes.shared.adapters.hetzner import HetznerError, release_id, site_config
from shapes.shared.adapters.outcome import Live, Staged
from cli.infra.dns import Action
from cli.sync.corpus.box import BoxError

BOX = "203.0.113.7"
SITES = "/opt/cs/sites"
D = f"{SITES}/www.moui.io"
SNIPPET = f"{SITES}/www.moui.io.caddy"
A, B, C = "a" * 16, "b" * 16, "c" * 16
COMPOSE_CADDYFILE = "/opt/cs/infrastructure/corpus-server/caddy/Caddyfile"
CADDYFILE = ("{\n\temail ops@moui.co\n}\n{$DOMAIN} {\n\treverse_proxy gate:8080\n}\n"
             "ask.moui.co {\n\trespond 204\n}\nimport /srv/sites/*.caddy\n")


def _manifest(path, aliases=(), spa=False):
    return json.dumps({"publish_path": path, "spa": spa, "aliases": list(aliases)}, sort_keys=True)


class FakeBox:
    def __init__(self, files=None, links=None, releases=None, reload_fails=False,
                 validate_fails=False, caddyfile=CADDYFILE, sites_mounted=True, stale=(),
                 race=False, cleanup_fails=False, rm_fails=False, lock_held=False):
        self.lock_held = lock_held
        self.caddyfile, self.sites_mounted, self.stale = caddyfile, sites_mounted, set(stale)
        self.race, self.cleanup_fails, self.rm_fails = race, cleanup_fails, rm_fails
        self.files = dict(files or {})
        self.links = dict(links or {})                    # link path -> relative target
        self.dirs = {k: list(v) for k, v in (releases or {}).items()}   # oldest first
        self.reload_fails, self.validate_fails = reload_fails, validate_fails
        self.ops, self.cmds, self.uploads, self.locked = [], [], [], False

    def ssh_exec(self, remote, cmd):
        self.cmds.append((cmd, self.locked))
        if m := re.fullmatch(r"if \[ -L (\S+) \]; then readlink \1; fi", cmd):
            return self.links[m[1]] + "\n" if m[1] in self.links else ""
        if m := re.fullmatch(r"test -d (\S+)/([^/\s]+) && echo present \|\| true", cmd):
            return "present\n" if m[2] in self.dirs.get(m[1], []) else ""
        if m := re.fullmatch(r"test -e (\S+) && echo present \|\| true", cmd):
            return "present\n" if m[1] in self.files else ""
        if m := re.fullmatch(r"mv -T (\S+)(\.part-[0-9a-f]{12}) \1 && touch \1", cmd):
            d, name = m[1].rsplit("/", 1)
            if name in self.dirs[d]:
                raise BoxError("mv: cannot move: Directory not empty")
            self.dirs[d].remove(name + m[2])
            self.dirs[d].append(name)
            return ""
        if m := re.fullmatch(r"ln -sfn (\S+) (\S+)\.next && mv -Tf \2\.next \2", cmd):
            self.links[m[2]] = m[1]
            self.ops.append("flip")
            return ""
        if m := re.fullmatch(r'for f in (\S+)/\*\.json; do .*', cmd):
            d = m[1]
            return "".join(f"==> {k}\n{v}\n" for k, v in sorted(self.files.items())
                           if k.rsplit("/", 1)[0] == d and k.endswith(".json"))
        if m := re.fullmatch(r"if \[ -e (\S+) \]; then echo present; cat \1; else echo absent; fi", cmd):
            return f"present\n{self.files[m[1]]}" if m[1] in self.files else "absent\n"
        if m := re.fullmatch(r"if \[ -e (\S+) \]; then cp \1 \1\.prev; else rm -f \1\.prev; fi", cmd):
            if m[1] in self.files:
                self.files[m[1] + ".prev"] = self.files[m[1]]
            else:
                self.files.pop(m[1] + ".prev", None)
            return ""
        if m := re.fullmatch(r"if \[ -e (\S+)\.prev \]; then mv \1\.prev \1; else rm -f \1; fi", cmd):
            if m[1] + ".prev" in self.files:
                self.files[m[1]] = self.files.pop(m[1] + ".prev")
            else:
                self.files.pop(m[1], None)
            self.ops.append("restore")
            return ""
        if m := re.fullmatch(r"cat (\S+)", cmd):
            assert m[1] == COMPOSE_CADDYFILE
            return self.caddyfile
        if m := re.fullmatch(r'rm -rf (\S+) && mkdir -p \1 && for f in (\S+)/\*\.caddy; do '
                             r'.*\[ "\$f" = (\S+) \].*', cmd):
            vdir, sites, own = m[1], m[2], m[3]
            self._rm([vdir])
            for k in [k for k in self.files if k.rsplit("/", 1)[0] == sites
                      and k.endswith(".caddy") and k != own]:
                self.files[f"{vdir}/{k.rsplit('/', 1)[1]}"] = self.files[k]
            return ""
        if m := re.search(r"exec -T caddy test -r (\S+)$", cmd):
            if not self.sites_mounted:
                raise BoxError("exit status 1")
            assert self._host(m[1]) in self.files
            return ""
        if m := re.search(r"exec -T caddy caddy validate --config (\S+) --adapter caddyfile$", cmd):
            self.ops.append("validate")
            return self._validate(self._host(m[1]), m[1].rsplit("/", 1)[0])
        if self.cleanup_fails and re.fullmatch(r"rm -rf \S+/\.validate/\S+", cmd):
            raise BoxError("rm: device busy")
        if m := re.fullmatch(r"find (\S+) -mindepth 1 -maxdepth 1 -name '\*\.part-\*' "
                             r"-mmin \+30 -exec rm -rf -- \{\} \+", cmd):
            for name in [n for n in self.dirs.get(m[1], []) if n in self.stale]:
                self.dirs[m[1]].remove(name)
            return ""
        if "caddy reload" in cmd:
            self.ops.append("reload")
            if self.reload_fails:
                raise BoxError("caddy: adapting config: bad")
            return ""
        if m := re.fullmatch(r"cd (\S+) && ls -1t", cmd):
            return "".join(n + "\n" for n in reversed(self.dirs.get(m[1], [])))
        if m := re.fullmatch(r"cd (\S+) && rm -rf -- (.+)", cmd):
            for name in m[2].split():
                self.dirs[m[1]].remove(name)
            self.ops.append("prune")
            return ""
        if m := re.fullmatch(r"mv -f (\S+\.caddy)\.tmp-[0-9a-f]{12} \1", cmd):
            self.files[m[1]] = self.files.pop(cmd.split()[2])
            self.ops.append("site")
            return ""
        if cmd.startswith("mkdir -p "):
            return ""
        if cmd.startswith("rm "):
            if self.rm_fails and "/mounts/" in cmd:
                raise BoxError("rm: read-only file system")
            return self._rm([w for w in cmd.split() if w.startswith("/")])
        raise AssertionError(f"FakeBox does not model: {cmd}")

    @staticmethod
    def _host(container_path):
        return container_path.replace("/srv/sites", SITES, 1)

    def _validate(self, caddyfile_path, import_dir_in_container):
        """Whole-config check, simply: the Caddyfile must import exactly the
        validation dir, and no site address may be declared twice."""
        cf = self.files[caddyfile_path]
        assert [l for l in cf.splitlines() if l.startswith("import ")] == \
            [f"import {import_dir_in_container}/*.caddy"]
        vdir = caddyfile_path.rsplit("/", 1)[0]
        texts = [cf] + [v for k, v in sorted(self.files.items())
                        if k.rsplit("/", 1)[0] == vdir and k.endswith(".caddy")]
        addrs = [l[:-2] for t in texts for l in t.splitlines()
                 if l.endswith(" {") and not l.startswith(("\t", " "))]
        dup = sorted({a for a in addrs if addrs.count(a) > 1})
        if dup:
            raise BoxError(f"ambiguous site definition: {dup[0]}")
        if self.validate_fails:
            raise BoxError("caddy: adapting config: bad")
        return ""

    def _rm(self, paths):
        kinds = set()
        for path in paths:
            for k in [k for k in self.files if k == path or k.startswith(path + "/")]:
                del self.files[k]
                if "/.validate/" not in k and not k.endswith(".prev"):
                    kinds.add("rm-site" if k.endswith(".caddy") else "rm-mount")
            for k in [k for k in self.links if k == path or k.startswith(path + "/")]:
                del self.links[k]; kinds.add("rm-mount")
            for k in [k for k in self.dirs if k == path or k.startswith(path + "/")]:
                if self.dirs.pop(k):
                    kinds.add("rm-mount")
            parent, name = path.rsplit("/", 1)
            if name in self.dirs.get(parent, []):
                self.dirs[parent].remove(name)
        self.ops += sorted(kinds)
        return ""

    def ship_version(self, remote, dist, version_dir, link_dest):
        d, name = version_dir.rsplit("/", 1)
        self.dirs.setdefault(d, []).append(name)
        if self.race:                          # a concurrent identical build lands first
            self.dirs[d].append(name.split(".part-")[0])
        self.uploads.append((version_dir, link_dest))
        self.ops.append("upload")

    def put_file(self, remote, content, dest):
        self.files[dest] = content
        if dest.endswith(".json"):
            self.ops.append("manifest")
        elif "/.validate/" not in dest:
            assert re.search(r"\.caddy\.tmp-[0-9a-f]{12}$", dest), f"non-atomic write: {dest}"

    def acquire_lock(self, remote, lockfile, *, label, target_ref=""):
        assert label == "grove deploy"
        if self.lock_held:
            raise BoxError(f"another {label} holds the lock (1000 /es)")
        assert not self.locked
        self.locked = True
        self.ops.append("lock")

    def release_lock(self, remote, lockfile):
        self.locked = False
        self.ops.append("unlock")


class FakeDns:
    def __init__(self, kinds, ops, take=False):
        self.kinds, self.ops, self.take = kinds, ops, take
        self.applied, self.names = False, None

    def plan(self, names, address):
        self.names = list(names)
        return [Action(n, "moui.io", self.kinds[n], (), address) for n in names]

    def refused(self, actions):
        return [] if self.take else [a for a in actions if a.kind == "replace"]

    def apply(self, actions):
        self.applied = True
        self.ops.append("dns")


REMOTE = "hetzner/moui-web"


def _config(dns, declared=("/",), elsewhere=None, **kw):
    """declared: paths declared on this remote; elsewhere: {path: [(remote, file)]}."""
    mounts = {p: [(REMOTE, "infrastructure/targets/en.yaml")] for p in declared}
    for p, decls in (elsewhere or {}).items():
        mounts[p] = sorted(mounts.get(p, []) + decls)
    return {"host": "ask.moui.co", "user": "root", "path": "/opt/cs",
            "domain": "www.moui.io", "dns": dns, "declared_mounts": mounts,
            "remote_id": REMOTE, **kw}


@pytest.fixture
def dist(tmp_path):
    (tmp_path / "index.html").write_text("hi")
    return tmp_path


def _wire(monkeypatch, fake, verify_ok=True):
    for fn in ("ssh_exec", "ship_version", "put_file", "acquire_lock", "release_lock"):
        monkeypatch.setattr(hetzner.box, fn, getattr(fake, fn))
    monkeypatch.setattr(hetzner, "_box_address", lambda host: BOX)
    seen = {}

    def verify(domain, publish_path, address, rid):
        seen["verify"] = (domain, publish_path, address, rid)
        fake.ops.append("verify")
        if not verify_ok:
            raise HetznerError("live on box, HTTPS check failed: 000")
    monkeypatch.setattr(hetzner, "_verify", verify)
    return seen


def test_new_domain_full_flow_in_order(monkeypatch, dist):
    fake = FakeBox()
    dns = FakeDns({"www.moui.io": "create"}, fake.ops)
    seen = _wire(monkeypatch, fake)
    out = hetzner.deploy(dist, _config(dns), "/")
    assert out == Live("https://www.moui.io/")
    assert fake.ops == ["upload", "lock", "flip", "manifest", "validate", "dns", "site",
                        "reload", "unlock", "verify", "lock", "unlock"]
    assert seen["verify"][:3] == ("www.moui.io", "/", BOX)
    rid = seen["verify"][3]
    assert (dist / hetzner.RELEASE_MARKER).read_text().strip() == rid
    assert "root * /srv/sites/www.moui.io/mounts/_root" in fake.files[SNIPPET]
    assert not any("/.validate/" in k for k in fake.files)
    assert json.loads(fake.files[f"{D}/mounts/_root.json"]) == {     # the symlink holds the release
        "publish_path": "/", "spa": False, "aliases": []}
    assert fake.links[f"{D}/mounts/_root"] == f"../releases/_root/{rid}"


def test_command_shapes_upload_flip_prune(monkeypatch, dist):
    fake = FakeBox(links={f"{D}/mounts/_root": f"../releases/_root/{A}"},
                   releases={f"{D}/releases/_root": [C, A, B + ".part-0123456789ab",
                                                     C + ".part-aaaaaaaaaaaa"]},
                   files={f"{D}/mounts/_root.json": _manifest("/")},
                   stale={C + ".part-aaaaaaaaaaaa"})
    dns = FakeDns({"www.moui.io": "keep"}, fake.ops)
    _wire(monkeypatch, fake)
    hetzner.deploy(dist, _config(dns), "/")
    rid = release_id(dist)
    cmds = [c for c, _ in fake.cmds]
    # upload: into a unique <rid>.part-<12 hex>, hardlinked against the live release, renamed
    [(part, link_dest)] = fake.uploads
    assert re.fullmatch(rf"{D}/releases/_root/{rid}\.part-[0-9a-f]{{12}}", part)
    assert link_dest == f"{D}/releases/_root/{A}"
    assert f"mv -T {part} {D}/releases/_root/{rid} && touch {D}/releases/_root/{rid}" in cmds
    # flip: relative target, atomic rename
    assert (f"ln -sfn ../releases/_root/{rid} {D}/mounts/_root.next && "
            f"mv -Tf {D}/mounts/_root.next {D}/mounts/_root") in cmds
    # prune: under the lock, hex names only; a .part only once stale (another deploy's
    # in-flight upload survives)
    prunes = [(c, locked) for c, locked in fake.cmds if c.startswith(f"cd {D}/releases/_root && rm")]
    assert prunes == [(f"cd {D}/releases/_root && rm -rf -- {C}", True)]
    assert [locked for c, locked in fake.cmds if c.startswith("find ")] == [True]
    assert sorted(fake.dirs[f"{D}/releases/_root"]) == sorted([A, rid, B + ".part-0123456789ab"])


def test_identical_redeploy_uploads_nothing_and_keeps_n_minus_1(monkeypatch, dist):
    rid = release_id(dist)
    fake = FakeBox(links={f"{D}/mounts/_root": f"../releases/_root/{rid}"},
                   releases={f"{D}/releases/_root": [C, A, rid]},
                   files={f"{D}/mounts/_root.json": _manifest("/")})
    dns = FakeDns({"www.moui.io": "keep"}, fake.ops)
    _wire(monkeypatch, fake)
    hetzner.deploy(dist, _config(dns), "/")
    assert "upload" not in fake.ops
    assert sorted(fake.dirs[f"{D}/releases/_root"]) == sorted([A, rid])


def test_dns_elsewhere_without_take_stages_only(monkeypatch, dist, capsys):
    fake = FakeBox()
    dns = FakeDns({"www.moui.io": "replace"}, fake.ops)
    seen = _wire(monkeypatch, fake)
    out = hetzner.deploy(dist, _config(dns), "/")
    assert "site" not in fake.ops and "reload" not in fake.ops and "validate" not in fake.ops
    assert not dns.applied and "verify" not in seen
    assert fake.ops[-1] == "unlock"
    assert isinstance(out, Staged) and out.url == "https://www.moui.io/"
    assert "staged" in out.reason and "--take-dns" in out.reason
    assert capsys.readouterr().err == ""          # the rail reports it, once


def test_dns_elsewhere_with_existing_site_reports_live(monkeypatch, dist, capsys):
    fake = FakeBox(links={f"{D}/mounts/_root": f"../releases/_root/{A}"},
                   releases={f"{D}/releases/_root": [A]},
                   files={f"{D}/mounts/_root.json": _manifest("/"),
                          SNIPPET: site_config("www.moui.io", [json.loads(_manifest("/"))])})
    dns = FakeDns({"www.moui.io": "replace"}, fake.ops)
    _wire(monkeypatch, fake)
    out = hetzner.deploy(dist, _config(dns), "/")
    assert out == Live("https://www.moui.io/")
    assert "site" not in fake.ops and not dns.applied
    err = capsys.readouterr().err
    assert f"release {release_id(dist)} is live for / through the existing site" in err
    assert "--take-dns" in err and "staged" not in err


def test_take_with_missing_declared_mount_refuses(monkeypatch, dist):
    fake = FakeBox()
    dns = FakeDns({"www.moui.io": "replace"}, fake.ops, take=True)
    _wire(monkeypatch, fake)
    with pytest.raises(HetznerError, match=r"/hub.*already flipped"):
        hetzner.deploy(dist, _config(dns, declared=("/", "/hub")), "/")
    assert not dns.applied and fake.ops[-1] == "unlock"


PITCH = {"/pitch": [("codeberg/moui-pages", "infrastructure/targets/moui/decks/pitch.yaml")]}


def test_take_names_other_remote_declarations_and_switches(monkeypatch, dist, capsys):
    # A declaration on another remote is not a live site: it is named, it does not block.
    fake = FakeBox({f"{D}/mounts/hub.json": _manifest("/hub")})
    dns = FakeDns({"www.moui.io": "replace"}, fake.ops, take=True)
    _wire(monkeypatch, fake)
    hetzner.deploy(dist, _config(dns, declared=("/", "/hub"), elsewhere=PITCH), "/")
    assert dns.applied and "site" in fake.ops
    err = capsys.readouterr().err
    assert ("also declared for www.moui.io on other remotes — once DNS moves the box serves "
            "only its own mounts: /pitch on codeberg/moui-pages "
            "(infrastructure/targets/moui/decks/pitch.yaml)") in err


def test_staged_reason_names_other_remote_declarations(monkeypatch, dist):
    fake = FakeBox()
    dns = FakeDns({"www.moui.io": "replace"}, fake.ops)
    _wire(monkeypatch, fake)
    out = hetzner.deploy(dist, _config(dns, elsewhere=PITCH), "/")
    assert isinstance(out, Staged)
    assert "/pitch on codeberg/moui-pages" in out.reason


def test_other_remote_declarations_do_not_block_without_a_replace(monkeypatch, dist):
    fake = FakeBox()
    dns = FakeDns({"www.moui.io": "create"}, fake.ops)
    _wire(monkeypatch, fake)
    hetzner.deploy(dist, _config(dns, elsewhere={"/pitch": [("codeberg/c", "t.yaml")]}), "/")
    assert dns.applied


def test_take_with_all_mounts_present_switches(monkeypatch, dist):
    other = {f"{D}/mounts/hub.json": _manifest("/hub")}
    fake = FakeBox(other)
    dns = FakeDns({"www.moui.io": "replace"}, fake.ops, take=True)
    _wire(monkeypatch, fake)
    hetzner.deploy(dist, _config(dns, declared=("/", "/hub/")), "/")   # canonicalised
    assert dns.applied and "reload" in fake.ops
    assert "handle_path /hub/*" in fake.files[SNIPPET]
    assert "mounts/_root" in fake.files[SNIPPET]


def test_validate_failure_changes_nothing(monkeypatch, dist):
    fake = FakeBox(validate_fails=True)
    dns = FakeDns({"www.moui.io": "create"}, fake.ops)
    _wire(monkeypatch, fake)
    with pytest.raises(HetznerError, match="DNS unchanged, live site unchanged"):
        hetzner.deploy(dist, _config(dns), "/")
    assert not dns.applied and "site" not in fake.ops and "reload" not in fake.ops
    assert SNIPPET not in fake.files
    assert not any("/.validate/" in k for k in fake.files)
    assert fake.ops[-1] == "unlock"


def test_reload_failure_after_dns_move_says_so(monkeypatch, dist):
    fake = FakeBox(reload_fails=True)
    dns = FakeDns({"www.moui.io": "create"}, fake.ops)
    _wire(monkeypatch, fake)
    with pytest.raises(HetznerError, match=r"previous config restored.*DNS now points at the box"):
        hetzner.deploy(dist, _config(dns), "/")
    assert fake.ops[-2:] == ["restore", "unlock"]
    assert fake.ops.index("validate") < fake.ops.index("dns")


def test_reload_failure_without_dns_change(monkeypatch, dist):
    fake = FakeBox(reload_fails=True)
    dns = FakeDns({"www.moui.io": "keep"}, fake.ops)
    _wire(monkeypatch, fake)
    with pytest.raises(HetznerError, match="previous config restored") as exc:
        hetzner.deploy(dist, _config(dns), "/")
    assert "DNS now points" not in str(exc.value)


def test_verify_failure_prints_exact_rollback(monkeypatch, dist):
    link = f"{D}/mounts/_root"
    fake = FakeBox(links={link: f"../releases/_root/{A}"},
                   releases={f"{D}/releases/_root": [A]},
                   files={f"{D}/mounts/_root.json": _manifest("/")})
    dns = FakeDns({"www.moui.io": "keep"}, fake.ops)
    _wire(monkeypatch, fake, verify_ok=False)
    with pytest.raises(HetznerError) as exc:
        hetzner.deploy(dist, _config(dns), "/")
    assert (f"roll back with: ssh root@ask.moui.co 'ln -sfn ../releases/_root/{A} {link}.next "
            f"&& mv -Tf {link}.next {link}'") in str(exc.value)
    assert "prune" not in fake.ops


def test_foreign_symlink_target_throws(monkeypatch, dist):
    fake = FakeBox(links={f"{D}/mounts/_root": "/elsewhere/x"})
    dns = FakeDns({"www.moui.io": "keep"}, fake.ops)
    _wire(monkeypatch, fake)
    with pytest.raises(HetznerError, match="/elsewhere/x"):
        hetzner.deploy(dist, _config(dns), "/")


def test_malformed_manifest_names_the_file(monkeypatch, dist):
    bad = f"{D}/mounts/es.json"
    fake = FakeBox({bad: "{not json"})
    dns = FakeDns({"www.moui.io": "keep"}, fake.ops)
    _wire(monkeypatch, fake)
    with pytest.raises(HetznerError, match=re.escape(bad)):
        hetzner.deploy(dist, _config(dns), "/")
    assert fake.ops[-1] == "unlock"


def test_manifest_missing_fields_names_the_file(monkeypatch, dist):
    bad = f"{D}/mounts/es.json"
    fake = FakeBox({bad: json.dumps({"publish_path": "/es", "aliases": []})})
    dns = FakeDns({"www.moui.io": "keep"}, fake.ops)
    _wire(monkeypatch, fake)
    with pytest.raises(HetznerError, match=re.escape(bad) + ".*spa"):
        hetzner.deploy(dist, _config(dns), "/")


def test_nested_deploy_with_aliases_throws(monkeypatch, dist):
    fake = FakeBox()
    dns = FakeDns({"www.moui.io": "keep"}, fake.ops)
    _wire(monkeypatch, fake)
    with pytest.raises(HetznerError, match="aliases"):
        hetzner.deploy(dist, _config(dns, aliases=["moui.io"]), "/es")
    assert fake.ops == []


def test_nested_deploy_uses_root_aliases_and_dns_for_domain_only(monkeypatch, dist):
    fake = FakeBox({f"{D}/mounts/_root.json": _manifest("/", aliases=["moui.io"])})
    dns = FakeDns({"www.moui.io": "keep"}, fake.ops)
    _wire(monkeypatch, fake)
    out = hetzner.deploy(dist, _config(dns, declared=("/", "/es")), "/es/")
    assert out == Live("https://www.moui.io/es/")
    assert dns.names == ["www.moui.io"]
    assert "moui.io {\n" in fake.files[SNIPPET]
    assert "\tredir https://www.moui.io{uri} 301\n}" in fake.files[SNIPPET]
    assert json.loads(fake.files[f"{D}/mounts/es.json"])["aliases"] == []
    assert json.loads(fake.files[f"{D}/mounts/es.json"])["publish_path"] == "/es"


def test_missing_injection_throws(dist):
    cfg = _config(FakeDns({}, []))
    del cfg["dns"]
    with pytest.raises(HetznerError, match="'dns'"):
        hetzner.deploy(dist, cfg, "/")


# --- unpublish -------------------------------------------------------------

def _two_mounts(**kw):
    root_m, es_m = json.loads(_manifest("/")), json.loads(_manifest("/es"))
    return FakeBox(
        files={f"{D}/mounts/_root.json": _manifest("/"), f"{D}/mounts/es.json": _manifest("/es"),
               SNIPPET: site_config("www.moui.io", [root_m, es_m])},
        links={f"{D}/mounts/_root": f"../releases/_root/{A}", f"{D}/mounts/es": f"../releases/es/{B}"},
        releases={f"{D}/releases/_root": [A], f"{D}/releases/es": [B]}, **kw)


def test_unpublish_with_remaining_mounts_reroutes_before_deleting(monkeypatch):
    fake = _two_mounts()
    _wire(monkeypatch, fake)
    hetzner.unpublish(_config(None), "/es")
    assert fake.ops == ["lock", "validate", "site", "reload", "rm-mount", "unlock"]
    assert "/es" not in fake.files[SNIPPET] and "mounts/_root" in fake.files[SNIPPET]
    assert f"{D}/mounts/es.json" not in fake.files and f"{D}/mounts/es" not in fake.links
    assert f"{D}/releases/es" not in fake.dirs
    assert fake.links[f"{D}/mounts/_root"] == f"../releases/_root/{A}"
    assert fake.dirs[f"{D}/releases/_root"] == [A]


def test_unpublish_last_mount_removes_site_then_files(monkeypatch):
    fake = FakeBox(files={f"{D}/mounts/_root.json": _manifest("/"),
                          SNIPPET: site_config("www.moui.io", [json.loads(_manifest("/"))])},
                   links={f"{D}/mounts/_root": f"../releases/_root/{A}"},
                   releases={f"{D}/releases/_root": [A]})
    _wire(monkeypatch, fake)
    hetzner.unpublish(_config(None), "/")
    assert fake.ops == ["lock", "rm-site", "reload", "rm-mount", "unlock"]
    assert not fake.files and not fake.links and not any(fake.dirs.values())


def test_unpublish_reload_failure_keeps_files_and_says_so(monkeypatch):
    fake = _two_mounts(reload_fails=True)
    _wire(monkeypatch, fake)
    with pytest.raises(HetznerError, match=r"previous config restored.*/es is still served"):
        hetzner.unpublish(_config(None), "/es")
    assert "rm-mount" not in fake.ops and fake.ops[-1] == "unlock"
    assert f"{D}/mounts/es.json" in fake.files and "handle_path /es/*" in fake.files[SNIPPET]


def test_unpublish_missing_mount_throws(monkeypatch):
    fake = FakeBox()
    _wire(monkeypatch, fake)
    with pytest.raises(HetznerError, match="/hub"):
        hetzner.unpublish(_config(None), "/hub")
    assert fake.ops[-1] == "unlock"


def test_unpublish_of_staged_domain_writes_no_site(monkeypatch):
    fake = _two_mounts()
    del fake.files[SNIPPET]                       # DNS was never taken: no site on the box
    _wire(monkeypatch, fake)
    hetzner.unpublish(_config(None), "/es")
    assert "site" not in fake.ops and "reload" not in fake.ops and "validate" not in fake.ops
    assert f"{D}/mounts/es.json" not in fake.files


# --- whole-config validation, staging, review round 2 -----------------------

def test_alias_colliding_with_another_snippet_fails_before_dns(monkeypatch, dist):
    fake = FakeBox({f"{SITES}/other.io.caddy": "moui.io {\n\trespond 200\n}\n"})
    dns = FakeDns({"www.moui.io": "create", "moui.io": "create"}, fake.ops)
    _wire(monkeypatch, fake)
    with pytest.raises(HetznerError, match="DNS unchanged, live site unchanged.*ambiguous site definition: moui.io"):
        hetzner.deploy(dist, _config(dns, aliases=["moui.io"]), "/")
    assert not dns.applied and "site" not in fake.ops
    assert not any("/.validate/" in k for k in fake.files)


def test_domain_colliding_with_committed_caddyfile_fails_before_dns(monkeypatch, dist):
    fake = FakeBox(caddyfile=CADDYFILE + "www.moui.io {\n\trespond 200\n}\n")
    dns = FakeDns({"www.moui.io": "create"}, fake.ops)
    _wire(monkeypatch, fake)
    with pytest.raises(HetznerError, match="DNS unchanged, live site unchanged.*ambiguous"):
        hetzner.deploy(dist, _config(dns), "/")
    assert not dns.applied


def test_redeploy_excludes_own_snippet_and_drops_prev(monkeypatch, dist):
    root = json.loads(_manifest("/"))
    fake = FakeBox(links={f"{D}/mounts/_root": f"../releases/_root/{A}"},
                   releases={f"{D}/releases/_root": [A]},
                   files={f"{D}/mounts/_root.json": _manifest("/"),
                          SNIPPET: site_config("www.moui.io", [root]),
                          f"{SITES}/next.moui.co.caddy": "next.moui.co {\n\trespond 200\n}\n"})
    dns = FakeDns({"www.moui.io": "keep"}, fake.ops)
    _wire(monkeypatch, fake)
    hetzner.deploy(dist, _config(dns), "/")
    assert "reload" in fake.ops
    assert SNIPPET + ".prev" not in fake.files
    assert f"{SITES}/next.moui.co.caddy" in fake.files


def test_caddyfile_without_sites_import_throws(monkeypatch, dist):
    fake = FakeBox(caddyfile=CADDYFILE.replace("import /srv/sites/*.caddy\n", ""))
    dns = FakeDns({"www.moui.io": "create"}, fake.ops)
    _wire(monkeypatch, fake)
    with pytest.raises(HetznerError, match=re.escape("import /srv/sites/*.caddy")):
        hetzner.deploy(dist, _config(dns), "/")
    assert not dns.applied and not any("/.validate/" in k for k in fake.files)


def test_sites_mount_missing_in_container_throws(monkeypatch, dist):
    fake = FakeBox(sites_mounted=False)
    dns = FakeDns({"www.moui.io": "create"}, fake.ops)
    _wire(monkeypatch, fake)
    with pytest.raises(HetznerError, match="sites mount missing in the caddy container"):
        hetzner.deploy(dist, _config(dns), "/")
    assert not dns.applied


def test_cleanup_failure_does_not_mask_validation_failure(monkeypatch, dist):
    fake = FakeBox(validate_fails=True, cleanup_fails=True)
    dns = FakeDns({"www.moui.io": "create"}, fake.ops)
    _wire(monkeypatch, fake)
    with pytest.raises(HetznerError, match=r"DNS unchanged.*adapting config.*device busy"):
        hetzner.deploy(dist, _config(dns), "/")
    assert not dns.applied


def test_concurrent_identical_upload_is_treated_as_present(monkeypatch, dist):
    fake = FakeBox(race=True)
    dns = FakeDns({"www.moui.io": "keep"}, fake.ops)
    _wire(monkeypatch, fake)
    hetzner.deploy(dist, _config(dns), "/")
    assert fake.dirs[f"{D}/releases/_root"] == [release_id(dist)]     # our .part-* removed


def test_staged_deploy_also_prunes_under_lock(monkeypatch, dist):
    fake = FakeBox(links={f"{D}/mounts/_root": f"../releases/_root/{A}"},
                   releases={f"{D}/releases/_root": [C, A]},
                   files={f"{D}/mounts/_root.json": _manifest("/")})
    dns = FakeDns({"www.moui.io": "replace"}, fake.ops)
    _wire(monkeypatch, fake)
    hetzner.deploy(dist, _config(dns), "/")
    assert fake.ops[-2:] == ["prune", "unlock"]
    assert sorted(fake.dirs[f"{D}/releases/_root"]) == sorted([A, release_id(dist)])


def test_unpublish_file_removal_failure_after_reroute(monkeypatch):
    fake = _two_mounts(rm_fails=True)
    _wire(monkeypatch, fake)
    with pytest.raises(HetznerError, match="site no longer routes /es; file removal failed"):
        hetzner.unpublish(_config(None), "/es")
    assert "reload" in fake.ops and fake.ops[-1] == "unlock"


def test_unpublish_root_with_nested_left_names_orphaned_aliases(monkeypatch, capsys):
    fake = _two_mounts()
    fake.files[f"{D}/mounts/_root.json"] = _manifest("/", aliases=["moui.io"])
    _wire(monkeypatch, fake)
    hetzner.unpublish(_config(None), "/")
    assert "handle_path /es/*" in fake.files[SNIPPET] and "\nmoui.io {" not in fake.files[SNIPPET]
    assert "moui.io" in capsys.readouterr().err


def test_unpublish_validates_the_whole_config(monkeypatch):
    fake = _two_mounts(caddyfile=CADDYFILE + "www.moui.io {\n\trespond 200\n}\n")
    _wire(monkeypatch, fake)
    with pytest.raises(HetznerError, match="ambiguous"):
        hetzner.unpublish(_config(None), "/es")
    assert "site" not in fake.ops and f"{D}/mounts/es.json" in fake.files


def test_snippet_write_is_atomic(monkeypatch, dist):
    fake = FakeBox()
    dns = FakeDns({"www.moui.io": "create"}, fake.ops)
    _wire(monkeypatch, fake)
    hetzner.deploy(dist, _config(dns), "/")
    [mv] = [c for c, _ in fake.cmds if c.startswith("mv -f ")]
    assert re.fullmatch(rf"mv -f {re.escape(SNIPPET)}\.tmp-[0-9a-f]{{12}} {re.escape(SNIPPET)}", mv)
    assert not any(".tmp-" in k for k in fake.files)


def test_held_domain_lock_is_a_hetzner_error_naming_state(monkeypatch, dist):
    fake = FakeBox(lock_held=True)
    dns = FakeDns({"www.moui.io": "create"}, fake.ops)
    _wire(monkeypatch, fake)
    with pytest.raises(HetznerError, match=r"not flipped.*DNS and the live site unchanged.*"
                                           r"another grove deploy holds the lock"):
        hetzner.deploy(dist, _config(dns), "/")
    assert "flip" not in fake.ops and not dns.applied


def test_held_domain_lock_on_unpublish_is_a_hetzner_error(monkeypatch):
    fake = _two_mounts(lock_held=True)
    _wire(monkeypatch, fake)
    with pytest.raises(HetznerError, match=r"nothing changed.*another grove deploy holds the lock"):
        hetzner.unpublish(_config(None), "/es")
