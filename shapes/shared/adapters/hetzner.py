# Copyright (C) 2026 Sensata Research GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""Hetzner box deploy adapter — the box serves the grove.

Uploads an immutable release into the box's sites root (box_layout), flips the
mount's symlink, validates the domain's Caddy site generated from every mount
manifest on the box, ensures DNS through the injected `dns` capability, writes
the site, reloads the stack's Caddy, and verifies the release over HTTPS
against the box address. One mount's deploy never touches another mount on the
same domain. No fallbacks.

Layout under <sites>/ (container path /srv/sites):
  <domain>.caddy                         generated from the manifests
  .validate/<domain>/                    whole-config validation copy, outside the import glob
  <domain>/mounts/<slug>.json            {publish_path, spa, aliases}
  <domain>/mounts/<slug> -> ../releases/<slug>/<id>     relative: resolves in-container
  <domain>/releases/<slug>/<id>/

Aliases belong to the root mount only: they redirect the whole host.
"""
import hashlib
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from cli.infra.box_layout import box_layout
from shapes.shared.adapters.outcome import Live, Staged
from cli.sync.corpus import box
from cli.sync.corpus.box import BoxError

REQUIRES = ("dns", "declared_mounts", "remote_id")   # injected by the deploy rail
CONTAINER_SITES = "/srv/sites"              # contract with infrastructure/corpus-server/docker-compose.yml
RELEASE_MARKER = "_release.txt"
SITES_IMPORT = f"import {CONTAINER_SITES}/*.caddy"   # the committed Caddyfile's line for grove sites
# An upload staging dir older than this has crashed. Same horizon as a stale
# sync lock (cli/sync/corpus/box.py _LOCK_STALE_S).
STALE_PART_S = 1800


class HetznerError(Exception):
    pass


REQUIRED_FIELDS = ("host", "user", "path", "domain")
MANIFEST_FIELDS = ("publish_path", "spa", "aliases")   # the release is the symlink's target, nowhere else
_NAME = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+")
_SEGMENT = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")   # no "--": it joins segments in the slug
_RELEASE = re.compile(r"[0-9a-f]{16}")


def _aliases(config: dict) -> list:
    """Aliases are optional; when declared they must be a list."""
    if "aliases" not in config:
        return []
    if not isinstance(config["aliases"], list):
        raise HetznerError(f"hetzner aliases must be a list, got {config['aliases']!r}")
    return config["aliases"]


def _validate_config(config: dict) -> None:
    missing = [f for f in REQUIRED_FIELDS if not config.get(f)]
    if missing:
        raise HetznerError(f"hetzner config missing required fields: {', '.join(missing)}")
    aliases = _aliases(config)
    for name in [config["domain"], *aliases]:
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise HetznerError(f"not a plain lowercase DNS name: {name!r}")
    if config["domain"] in aliases:
        raise HetznerError(f"alias {config['domain']!r} is the domain itself")


def _segments(publish_path: str) -> list:
    if publish_path == "/":
        return []
    segments = publish_path.strip("/").split("/")
    if not publish_path.startswith("/") or not all(_SEGMENT.fullmatch(s) for s in segments):
        raise HetznerError(f"publish_path {publish_path!r} must be '/' or /lowercase-segments")
    return segments


def mount_slug(publish_path: str) -> str:
    segments = _segments(publish_path)
    return "--".join(segments) if segments else "_root"


def canonical_path(publish_path: str) -> str:
    """One spelling per mount: '/' or '/a/b' (no trailing slash)."""
    return "/" + "/".join(_segments(publish_path))


def release_id(dist: Path) -> str:
    """Content hash of the build: an identical build is the same release. The
    top-level marker is excluded (it carries the id); symlinks hash by target."""
    entries = []
    for dirpath, dirnames, filenames in os.walk(dist):       # never follows symlinks
        for name in dirnames + filenames:
            p = Path(dirpath) / name
            if p.is_symlink() or p.is_file():
                entries.append((p.relative_to(dist).as_posix(), p))
    h = hashlib.sha256()
    for rel, p in sorted(entries):
        if rel == RELEASE_MARKER:
            continue
        if p.is_symlink():
            h.update(b"L" + rel.encode() + b"\0" + os.readlink(p).encode() + b"\0")
        else:
            h.update(b"F" + rel.encode() + b"\0" + hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()[:16]


def _root_line(domain: str, slug: str, indent: str = "\t\t") -> str:
    return f"{indent}root * {CONTAINER_SITES}/{domain}/mounts/{slug}"


# No includeSubDomains: other subdomains of these names are not ours to pin.
HSTS = '\theader Strict-Transport-Security "max-age=31536000"'
SHELL_404 = "/404.html"   # contract with shapes/grove/exporters/build.py: the app shell for deep links


def site_config(domain: str, manifests: list) -> str:
    """The domain's Caddy site from every mount on the box. Nested mounts first,
    longest path first; the root mount (or a 404) last; the root mount's aliases
    301 to the domain. A 404 under a mount serves that mount's 404.html (the
    grove's app shell) with status 404, so deep links boot the SPA."""
    if not manifests:
        raise HetznerError(f"site_config for {domain}: no mounts")
    lines = [f"{domain} {{", "\tencode gzip", "\theader -Server", HSTS]
    nested = sorted((m for m in manifests if m["publish_path"] != "/"),
                    key=lambda m: -len(m["publish_path"]))
    for m in nested:
        p = m["publish_path"].rstrip("/")
        lines += [f"\tredir {p} {p}/ 308", f"\thandle_path {p}/* {{",
                  _root_line(domain, mount_slug(m["publish_path"]))]
        if m["spa"]:
            lines.append("\t\ttry_files {path} /index.html")
        lines += ["\t\tfile_server", "\t}"]
    root = [m for m in manifests if m["publish_path"] == "/"]
    lines.append("\thandle {")
    if root:
        lines.append(_root_line(domain, "_root"))
        if root[0]["spa"]:
            lines.append("\t\ttry_files {path} /index.html")
        lines.append("\t\tfile_server")
    else:
        lines.append("\t\terror 404")
    lines.append("\t}")
    lines.append("\thandle_errors 404 {")
    shell = [f"\t\t\trewrite * {SHELL_404}", "\t\t\tfile_server", "\t\t}"]
    for m in nested:
        lines += [f"\t\thandle_path {m['publish_path'].rstrip('/')}/* {{",
                  _root_line(domain, mount_slug(m["publish_path"]), "\t\t\t"), *shell]
    if root:
        lines += ["\t\thandle {", _root_line(domain, "_root", "\t\t\t"), *shell]
    lines += ["\t}", "}"]
    for alias in sorted(root[0]["aliases"]) if root else []:
        lines += [f"{alias} {{", HSTS, f"\tredir https://{domain}{{uri}} 301", "}"]
    return "\n".join(lines) + "\n"


VERIFY_TIMEOUT_S = 300   # first cert after a DNS switch; ACME resolvers honour the old record's TTL (300s)
VERIFY_INTERVAL_S = 5

q = shlex.quote


def _paths(config: dict, publish_path: str) -> dict:
    sites = box_layout(config)["sites"]
    domain, slug = config["domain"], mount_slug(publish_path)
    d = f"{sites}/{domain}"
    return {"sites": sites, "domain_dir": d, "slug": slug,
            "snippet": f"{sites}/{domain}.caddy", "lock": f"{sites}/{domain}.lock",
            "vdir": f"{sites}/.validate/{domain}",
            "vdir_in_container": f"{CONTAINER_SITES}/.validate/{domain}",
            "mounts": f"{d}/mounts", "manifest": f"{d}/mounts/{slug}.json",
            "link": f"{d}/mounts/{slug}", "releases": f"{d}/releases/{slug}"}


def _box_address(host: str) -> str:
    try:
        infos = {i[4][0] for i in socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)}
    except socket.gaierror as e:
        raise HetznerError(f"box host {host} does not resolve: {e}")
    if len(infos) != 1:
        raise HetznerError(f"box host {host} resolves to {sorted(infos)} — expected one IPv4 address")
    return infos.pop()


def _current_release(config: dict, p: dict) -> str | None:
    link = q(p["link"])
    target = box.ssh_exec(config, f"if [ -L {link} ]; then readlink {link}; fi").strip()
    if not target:
        return None
    m = re.fullmatch(rf"\.\./releases/{re.escape(p['slug'])}/([0-9a-f]{{16}})", target)
    if not m:
        raise HetznerError(f"{p['link']} points at {target!r}, not ../releases/{p['slug']}/"
                           f"<16 hex> — not a link this adapter wrote; fix it by hand")
    return m[1]


def _parse_manifest(name: str, text: str) -> dict:
    try:
        m = json.loads(text)
    except json.JSONDecodeError as e:
        raise HetznerError(f"manifest {name} is not JSON: {e}")
    if not isinstance(m, dict):
        raise HetznerError(f"manifest {name} is not an object")
    missing = [f for f in MANIFEST_FIELDS if f not in m]
    if missing:
        raise HetznerError(f"manifest {name} missing fields: {', '.join(missing)}")
    return m


def _read_manifests(config: dict, mounts_dir: str) -> list:
    # An unmatched glob is the only skipped case; a failing cat fails the call.
    out = box.ssh_exec(config, f'for f in {q(mounts_dir)}/*.json; do [ -e "$f" ] || continue; '
                               f'echo "==> $f"; cat "$f" || exit 1; echo; done')
    files, name = [], None
    for line in out.splitlines():
        if line.startswith("==> "):
            name = line[4:]
            files.append((name, []))
        elif name is None:
            if line.strip():
                raise HetznerError(f"unexpected output reading manifests in {mounts_dir}: {line!r}")
        else:
            files[-1][1].append(line)
    return [_parse_manifest(n, "\n".join(body)) for n, body in files]


def _read_snippet(config: dict, p: dict) -> str | None:
    s = q(p["snippet"])
    out = box.ssh_exec(config, f"if [ -e {s} ]; then echo present; cat {s}; else echo absent; fi")
    head, _, body = out.partition("\n")
    if head == "present":
        return body
    if head == "absent":
        return None
    raise HetznerError(f"unexpected output reading {p['snippet']}: {head!r}")


def _upload(config: dict, dist: Path, p: dict, rid: str, previous: str | None) -> None:
    final = f"{p['releases']}/{rid}"
    if box.ssh_exec(config, f"test -d {q(final)} && echo present || true").strip() == "present":
        return                                            # identical build already on the box
    part = f"{final}.part-{uuid4().hex[:12]}"           # unique: concurrent uploads never share
    link_dest = f"{p['releases']}/{previous}" if previous else None
    box.ship_version(config, dist, part, link_dest)
    try:
        # touch: the release dir's mtime is its arrival on the box (prune orders by it)
        box.ssh_exec(config, f"mv -T {q(part)} {q(final)} && touch {q(final)}")
    except BoxError:
        if box.ssh_exec(config, f"test -d {q(final)} && echo present || true").strip() != "present":
            raise
        box.ssh_exec(config, f"rm -rf {q(part)}")       # a concurrent identical build landed first


def _flip_command(p: dict, rid: str) -> str:
    target = f"../releases/{p['slug']}/{rid}"
    tmp = f"{p['link']}.next"
    return f"ln -sfn {q(target)} {q(tmp)} && mv -Tf {q(tmp)} {q(p['link'])}"


def _flip(config: dict, p: dict, rid: str, manifest: dict) -> None:
    box.ssh_exec(config, _flip_command(p, rid))
    box.put_file(config, json.dumps(manifest, sort_keys=True) + "\n", p["manifest"])


def _in_caddy(config: dict, command: str) -> str:
    layout = box_layout(config)
    return (f"cd {q(layout['compose_dir'])} && docker compose "
            f"--env-file {q(layout['env_file'])} exec -T caddy {command}")


def _reload(config: dict) -> None:
    layout = box_layout(config)
    box.caddy_reload(config, layout["compose_dir"], layout["env_file"])


def _validation_caddyfile(committed: str, vdir_in_container: str) -> str:
    """The committed Caddyfile with its grove-sites import pointed at the
    validation dir — the whole config as it would be with the candidate."""
    lines = committed.split("\n")
    hits = [i for i, line in enumerate(lines) if line.strip() == SITES_IMPORT]
    if len(hits) != 1:
        raise HetznerError(f"the committed Caddyfile must contain the line {SITES_IMPORT!r} "
                           f"exactly once (found {len(hits)})")
    i = hits[0]
    lines[i] = lines[i].replace(SITES_IMPORT, f"import {vdir_in_container}/*.caddy")
    return "\n".join(lines)


def _stage_and_validate(config: dict, p: dict, candidate: str) -> None:
    domain, vdir, cvdir = config["domain"], p["vdir"], p["vdir_in_container"]
    try:
        committed = box.ssh_exec(config, f"cat {q(box_layout(config)['caddyfile'])}")
        caddyfile = _validation_caddyfile(committed, cvdir)
        box.ssh_exec(config, f'rm -rf {q(vdir)} && mkdir -p {q(vdir)} && '
                             f'for f in {q(p["sites"])}/*.caddy; do [ -e "$f" ] || continue; '
                             f'[ "$f" = {q(p["snippet"])} ] && continue; '
                             f'cp "$f" {q(vdir)}/ || exit 1; done')
        box.put_file(config, candidate, f"{vdir}/{domain}.caddy")
        box.put_file(config, caddyfile, f"{vdir}/Caddyfile")   # no .caddy: never imports itself
    except BoxError as e:
        raise HetznerError(f"preparing validation for {domain} failed — "
                           f"DNS unchanged, live site unchanged: {e}")
    try:
        box.ssh_exec(config, _in_caddy(config, f"test -r {q(cvdir + '/Caddyfile')}"))
    except BoxError as e:
        raise HetznerError(f"sites mount missing in the caddy container (deploy the stack "
                           f"first) — DNS unchanged, live site unchanged: {e}")
    try:
        box.ssh_exec(config, _in_caddy(
            config, f"caddy validate --config {q(cvdir + '/Caddyfile')} --adapter caddyfile"))
    except BoxError as e:
        raise HetznerError(f"caddy rejected the generated site for {domain} — "
                           f"DNS unchanged, live site unchanged: {e}")


def _validate_site(config: dict, p: dict, candidate: str) -> None:
    """Validate the WHOLE config (committed Caddyfile + every other site + the
    candidate) before anything moves. The validation dir is always removed; a
    cleanup failure never masks the original error."""
    try:
        _stage_and_validate(config, p, candidate)
    except HetznerError as e:
        try:
            box.ssh_exec(config, f"rm -rf {q(p['vdir'])}")
        except BoxError as c:
            raise HetznerError(f"{e}; cleanup of {p['vdir']} also failed: {c}")
        raise
    try:
        box.ssh_exec(config, f"rm -rf {q(p['vdir'])}")
    except BoxError as c:
        raise HetznerError(f"validation passed but cleanup of {p['vdir']} failed — "
                           f"DNS unchanged, live site unchanged: {c}")


def _backup_site(config: dict, p: dict) -> None:
    s = q(p["snippet"])
    box.ssh_exec(config, f"if [ -e {s} ]; then cp {s} {s}.prev; else rm -f {s}.prev; fi")


def _restore_site(config: dict, p: dict) -> None:
    s = q(p["snippet"])
    box.ssh_exec(config, f"if [ -e {s}.prev ]; then mv {s}.prev {s}; else rm -f {s}; fi")


def _write_site(config: dict, p: dict, candidate: str, state: str) -> None:
    """Write the (validated) site and reload; on a rejected reload restore the
    previous site and throw naming `state` — what is true on the box now."""
    _backup_site(config, p)
    # Atomic: the tmp name is outside the *.caddy glob, so a concurrent validation
    # or reload never reads a half-written site.
    tmp = f"{p['snippet']}.tmp-{uuid4().hex[:12]}"
    box.put_file(config, candidate, tmp)
    box.ssh_exec(config, f"mv -f {q(tmp)} {q(p['snippet'])}")
    try:
        _reload(config)
    except BoxError as e:
        _restore_site(config, p)
        raise HetznerError(f"caddy reload failed for {config['domain']} — "
                           f"previous config restored; {state}: {e}")
    box.ssh_exec(config, f"rm -f {q(p['snippet'])}.prev")


def _verify(domain: str, publish_path: str, address: str, rid: str) -> None:
    url = f"https://{domain}{publish_path.rstrip('/')}/{RELEASE_MARKER}"
    deadline = time.monotonic() + VERIFY_TIMEOUT_S
    while True:
        try:
            r = subprocess.run(["curl", "-fsS", "--max-time", "10",
                                "--resolve", f"{domain}:443:{address}", url],
                               capture_output=True, text=True)
        except FileNotFoundError as e:
            raise HetznerError(f"cannot verify {url}: curl not found ({e})")
        if r.returncode == 0 and r.stdout.strip() == rid:
            return
        last = (r.stderr.strip() or f"served release {r.stdout.strip()!r}")[:120]
        if time.monotonic() + VERIFY_INTERVAL_S >= deadline:
            break
        time.sleep(VERIFY_INTERVAL_S)
    raise HetznerError(f"live on box, HTTPS check failed for {url}: {last}")


def _prune(config: dict, p: dict, rid: str, previous: str | None) -> None:
    """Under the lock, against live state: keep the current target, this release,
    the previous one, and the newest other release (N-1 survives an identical
    redeploy). Only 16-hex names are candidates; a .part-* staging dir only once
    older than STALE_PART_S — never another deploy's in-flight upload."""
    current = _current_release(config, p)
    names = box.ssh_exec(config, f"cd {q(p['releases'])} && ls -1t").split()
    releases = [n for n in names if _RELEASE.fullmatch(n)]
    newest_other = next((n for n in releases if n not in {current, rid}), None)
    keep = {current, rid, previous, newest_other} - {None}
    doomed = [n for n in releases if n not in keep]
    if doomed:
        box.ssh_exec(config, f"cd {q(p['releases'])} && rm -rf -- {' '.join(doomed)}")
    box.ssh_exec(config, f"find {q(p['releases'])} -mindepth 1 -maxdepth 1 -name '*.part-*' "
                         f"-mmin +{STALE_PART_S // 60} -exec rm -rf -- {{}} +")


def _lock(config: dict, p: dict, ref: str) -> None:
    """The per-domain lock around flip → site → reload, prune and unpublish."""
    box.acquire_lock(config, p["lock"], label="grove deploy", target_ref=ref)


def _check_injected(config: dict) -> None:
    for need in REQUIRES:
        if need not in config:
            raise HetznerError(f"the deploy rail did not inject '{need}' "
                               f"(hetzner REQUIRES {REQUIRES})")


def _declared(declared_mounts: dict) -> dict:
    """{canonical publish_path: [(remote_id, target_file)]} — one spelling per mount."""
    out: dict = {}
    for path, decls in declared_mounts.items():
        out.setdefault(canonical_path(path), []).extend(decls)
    return {p: sorted(set(d)) for p, d in out.items()}


def _guard(declared: dict, present: set, remote_id: str) -> list:
    """What blocks moving the domain onto the box: a path this remote declares that
    the box lacks."""
    missing = sorted(p for p, d in declared.items()
                     if any(r == remote_id for r, _ in d) and p not in present)
    if missing:
        return [f"declared mounts not on the box yet: {', '.join(missing)} — deploy those first"]
    return []


def _elsewhere(declared: dict, remote_id: str, domain: str) -> str | None:
    """Paths other remotes declare for this domain. A declaration is not a live site
    (Codeberg can claim www.moui.io while DNS points at GitHub), so they don't block;
    they are named so a live one isn't lost without a word."""
    lines = [f"{path} on {other} ({target_file})"
             for path in sorted(declared) for other, target_file in declared[path]
             if other != remote_id]
    if not lines:
        return None
    return (f"also declared for {domain} on other remotes — once DNS moves the box serves "
            f"only its own mounts: {'; '.join(lines)}")


def _routes(snippet: str | None, domain: str, slug: str) -> bool:
    return snippet is not None and _root_line(domain, slug) + "\n" in snippet


def deploy(dist_path: Path, config: dict, publish_path: str, *,
           force: bool = False, spa: bool = False) -> Live | Staged:
    """Staged when DNS points elsewhere, --take-dns was not given and no existing
    site routes the mount; Live otherwise (live through an existing site is
    noted on stderr: DNS still needs --take-dns)."""
    _validate_config(config)
    _check_injected(config)
    publish_path = canonical_path(publish_path)
    aliases = _aliases(config)
    if publish_path != "/" and aliases:
        raise HetznerError(f"aliases {aliases} redirect the whole host — they belong to the "
                           f"root mount, not {publish_path}")
    declared = _declared(config["declared_mounts"])
    p = _paths(config, publish_path)
    domain = config["domain"]
    names = [domain, *aliases]
    url = f"https://{domain}{publish_path.rstrip('/')}/"

    rid = release_id(dist_path)
    (dist_path / RELEASE_MARKER).write_text(rid + "\n")
    box.ssh_exec(config, f"mkdir -p {q(p['releases'])} {q(p['mounts'])}")
    previous = _current_release(config, p)
    try:
        _upload(config, dist_path, p, rid, previous)
    except BoxError as e:
        raise HetznerError(f"upload failed — live site unchanged: {e}")

    try:
        _lock(config, p, publish_path)
    except BoxError as e:
        raise HetznerError(f"release {rid} uploaded but not flipped — DNS and the live site "
                           f"unchanged: {e}")
    try:
        _flip(config, p, rid, {"publish_path": publish_path, "spa": spa, "aliases": aliases})
        manifests = _read_manifests(config, p["mounts"])
        address = _box_address(config["host"])
        dns = config["dns"]
        actions = dns.plan(names, address)
        refused = dns.refused(actions)
        if refused:
            listed = ", ".join(a.name for a in refused)
            live = _routes(_read_snippet(config, p), domain, p["slug"])
            if live:
                state = (f"release {rid} is live for {publish_path} through the existing site; "
                         f"DNS for {listed} not changed (needs --take-dns to point it at "
                         f"{address})")
            else:
                state = (f"staged {publish_path} on the box (release {rid}); DNS for {listed} "
                         f"points elsewhere, so the site is not switched — deploy with "
                         f"--take-dns to point it at {address}")
            notice = _elsewhere(declared, config["remote_id"], domain)
            if notice:
                state = f"{state}. Note: {notice}"
            try:
                _prune(config, p, rid, previous)
            except (BoxError, HetznerError) as e:
                raise HetznerError(f"{state}; prune failed: {e}")
            if not live:
                return Staged(url, state)
            print(state, file=sys.stderr)
            return Live(url)
        if any(a.kind == "replace" for a in actions):
            present = {canonical_path(m["publish_path"]) for m in manifests}
            blockers = _guard(declared, present, config["remote_id"])
            if blockers:
                raise HetznerError(
                    f"refusing to move {domain} onto the box: {'; '.join(blockers)}. "
                    f"{publish_path} was already flipped to release {rid} on the box; DNS "
                    f"and the Caddy site are unchanged")
            notice = _elsewhere(declared, config["remote_id"], domain)
            if notice:
                print(notice, file=sys.stderr)
        candidate = site_config(domain, manifests)
        _validate_site(config, p, candidate)
        dns.apply(actions)
        moved = any(a.kind != "keep" for a in actions)
        _write_site(config, p, candidate,
                    f"DNS now points at the box ({address})" if moved else "DNS unchanged")
    finally:
        box.release_lock(config, p["lock"])

    try:
        _verify(domain, publish_path, address, rid)
    except HetznerError as e:
        if previous and previous != rid:
            back = (f"roll back with: ssh {config['user']}@{config['host']} "
                    f"{q(_flip_command(p, previous))}")
        else:
            back = "no previous release to roll back to"
        raise HetznerError(f"{e}; {back}")
    try:
        _lock(config, p, f"prune {publish_path}")
        try:
            _prune(config, p, rid, previous)
        finally:
            box.release_lock(config, p["lock"])
    except (BoxError, HetznerError) as e:
        raise HetznerError(f"{url} live and verified; prune failed: {e}")
    return Live(url)


def unpublish(config: dict, publish_path: str) -> None:
    _validate_config(config)
    publish_path = canonical_path(publish_path)
    p = _paths(config, publish_path)
    domain = config["domain"]
    remove_mount = f"rm -f {q(p['link'])} {q(p['manifest'])} && rm -rf {q(p['releases'])}"
    box.ssh_exec(config, f"mkdir -p {q(p['sites'])}")
    try:
        _lock(config, p, f"unpublish {publish_path}")
    except BoxError as e:
        raise HetznerError(f"cannot unpublish {publish_path} from {domain}, nothing changed: {e}")
    try:
        if box.ssh_exec(config, f"test -e {q(p['manifest'])} && echo present || true"
                        ).strip() != "present":
            raise HetznerError(f"nothing to unpublish: no {publish_path} mount on {domain} "
                               f"({p['manifest']} does not exist)")
        manifests = _read_manifests(config, p["mounts"])
        remaining = [m for m in manifests if canonical_path(m["publish_path"]) != publish_path]
        gone = [m for m in manifests if canonical_path(m["publish_path"]) == publish_path]
        snippet = _read_snippet(config, p)
        still = f"{publish_path} is still served, its files untouched"
        if snippet is None:                     # staged only: no site to rewrite
            box.ssh_exec(config, remove_mount if remaining else f"rm -rf {q(p['domain_dir'])}")
        elif remaining:
            candidate = site_config(domain, remaining)
            _validate_site(config, p, candidate)
            _write_site(config, p, candidate, still)
            try:
                box.ssh_exec(config, remove_mount)
            except BoxError as e:
                raise HetznerError(f"site no longer routes {publish_path}; "
                                   f"file removal failed: {e}")
            if publish_path == "/" and gone[0]["aliases"]:
                print(f"{domain}: aliases {', '.join(gone[0]['aliases'])} went with the root "
                      f"mount — their DNS was not changed and may still point at the box, "
                      f"where they now have no site", file=sys.stderr)
        else:
            _backup_site(config, p)
            box.ssh_exec(config, f"rm -f {q(p['snippet'])}")
            try:
                _reload(config)
            except BoxError as e:
                _restore_site(config, p)
                raise HetznerError(f"caddy reload failed removing {domain} — previous config "
                                   f"restored; {still}: {e}")
            box.ssh_exec(config, f"rm -f {q(p['snippet'])}.prev && rm -rf {q(p['domain_dir'])}")
    finally:
        box.release_lock(config, p["lock"])
