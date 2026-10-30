# shapes/webapp/

**Layer:** Interface — instance "webapp"

Any source folder that builds itself into a static web app. The deck and the grove build a web app from data; a webapp brings its own engine. The shape runs the build the folder declares and hands the output to `mo deploy`, the same rail and adapters as every other shape.

## Contract

The folder declares its build in `webapp.yaml` (`schemas/webapp.v1.json`):

```yaml
instance: webapp
version: 0.1.0
schema: webapp.v1.json
build:              # commands, in order, run inside the folder; argv lists, no shell
  - [npm, ci]
  - [npm, run, build]
out: dist           # the built site, inside the folder; must hold index.html
```

The shape knows no engine: no npm, no bundler, no framework.

## Build

`exporters/build.py` validates `webapp.yaml`, runs each command, and returns `out`. It throws on:

- a missing or invalid `webapp.yaml`
- a command that is not found or exits non-zero (command, exit code and output in the error)
- `out` outside the folder, or `out/index.html` missing or not written by this build
- target settings a static webapp cannot honor: `encrypted: true`, `service_worker: true`, `crawlable` other than `none`

Paths are the app's concern. An app built with relative asset paths works at any `publish_path`.

## Use

```
mo webapp build content/<path>                 # local build, prints the output folder
mo deploy content/<path> <env> --dry-run       # target in infrastructure/targets/<path>.yaml
mo deploy content/<path> <env>
```
