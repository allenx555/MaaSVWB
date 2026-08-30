# MaaSVWB AI development guide

## Project scope

MaaSVWB automates Shadowverse: Worlds Beyond puzzle and battle tutorials on an Android
emulator. The product uses MaaFramework pipelines for recognition and a Python Agent for
semantic card and follower actions. The Avalonia application under `gui/` is the official
desktop frontend.

## MaaFramework skill

When changing `assets/interface.json`, `assets/resource/pipeline/`, MaaFramework
recognition/action configuration, Controller/Tasker integration, callbacks, or custom
Agent actions, use the project MaaFramework skill at
`.agents/skills/maaframework/SKILL.md`. Read that file completely before following its
references.

If the skill is absent, run `tools/setup_ai_dev.ps1`. Its exact upstream source and commit
are pinned in `tools/ai-tools.lock.json`. The downloaded reference is guidance only: the
current schemas under `deps/tools/`, `npx @nekosu/maa-tools check`, and project tests remain
the source of truth.

## Live emulator debugging

MaaMCP is an optional development tool, not a product dependency. Use it only when a task
benefits from inspecting a user-authorized emulator through screenshots, OCR, clicks, or
swipes. Do not control unrelated Windows applications. Prefer OCR before full screenshots,
stop background pipelines when finished, and never treat exploratory coordinate actions as
the final puzzle abstraction.

Record stable puzzle behavior as semantic solution actions such as `play_card`, `attack`,
and `select_target`. Keep raw coordinates in layouts or low-level fallback steps rather
than exposing them to solution authors.

## Required verification

Run `tools/test.ps1` after changing Python, catalogs, solutions, pipelines, AI tool pins, or
project instructions. Run the Avalonia build after changing `gui/`. Do not claim an
emulator workflow is verified unless it was actually executed against an authorized live
device.
