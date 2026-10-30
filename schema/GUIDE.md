# schema/

**Layer:** Data

Base JSON Schema type definitions for the moui platform. These are the root types — all content and manifests validate against schemas defined here.

## What belongs here

- `bite.v1.json` — base type all content extends
- `manifest.v1.json` — corpus manifest (moui.json) schema
- `shape.v1.json` — shape manifest schema

## What does not belong here

- Shape-specific schemas — those live in `shapes/<instance>/schemas/` and are deposited to `content/schema/` by `moui install`

## Validation

Run `moui check` to validate that moui.json and shape manifests conform to their schemas.
