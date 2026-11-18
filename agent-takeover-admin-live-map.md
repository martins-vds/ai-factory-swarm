# Migration swarm coordinator takeover

Updated 2026-11-06T19:09Z. This is a handoff, not new authorization or evidence of acceptance.

## Mission and authority

Continue the user's existing Claude-style migration-swarm orchestration using actual role workers, committed attributable evidence, independent exact-head review and actual executed CI. Do not write role outputs as a substitute for workers.

User selected the next application slice: **admin live map**, and explicitly requested committing and pushing changes.

Standing user authority covers merging independently verified harness-defect PRs and role-evidence-only PRs, including bounded normal pinned harness-fix rollouts. It does NOT approve unseen application plans, arbitrary application merges, new quirk rulings, credential transfer, gate waivers or fabricated human acceptance.

Application sequence: Analyst -> Characterizer -> Planner -> actual user plan approval -> implementation tickets/roles -> verification/acceptance -> genuine human flow check.

## Exact current repositories

- Harness source: `martins-vds/ai-factory-swarm`, main **9fcf4deb0565229bc4c3078e9da0c9bfece045c7**, tree **db4d5e74d056c69f401564d31d1fb812d4fd440c**.
- Migration target: `martins-vds/ai-factory-pilot-target`, main **5ee7df68b8ae6d66ac8c5a4f9824bae5be982542**, tree **19a005bbdd0b3b63b3312a6bac71b3eb6c245e1b**.
- Actual target MAIN installs harness9FC. Actual postmerge AFS42265898591 and setup42265898696 both SUCCESS at exact5EE.
- Frozen read-only application source: `eclipse-ee4j/cargotracker@f3beacf78de4f6d34edc4971ac87e38a5c6fe59d`.
- Main baseline after latest rollout: **830 committed paths / 46 historical YAML returns**.
- Accepted handling-registration slice113, prior genuine acceptance/signoff and completed coordinator results must remain unchanged.
- Research172/173 is explicitly excluded. Do not merge draft173 or start other frontier slices101/112.

## Latest live finding: graph run completed; review is next

The one explicitly focused NORMAL graph workflow is now completed SUCCESS:

https://github.com/martins-vds/ai-factory-pilot-target/actions/runs/42274481680

- Actual run HEAD:5EE.
- Inputs: `side=source`, `slice=""` (full), `domain_entry_points=src/main/webapp/admin/tracking/map.xhtml`.
- Model override OMITTED.
- Normal pinned CLI1.0.105, SDK1.0.28, Understand Anything4e6d3299017a7432da15957874992837a315c5b4, Graphify and JavaEE enrichment executed.
- Actual runner reports DEFERRED; actual subsequent post-enrichment checker reports **domain coverage: PASS**.
- Actual output branch **afs/graph-source-full-42274481680**, head **5df1e95ec8bf98bf7e1fbd0fad9913a15cad90c5**.
- SNAPSHOT correctly identifies sourceF3, full scope, pinned upstream4e6d329 and actual run42274481680.
- Workflow's PR creation FAILED with `GraphQL: GitHub Actions is not permitted to create or approve pull requests (createPullRequest)`. Branch was successfully pushed. No graph PR exists as of this handoff.
- **Do not redispatch.** The workflow explicitly instructs opening the existing branch's PR manually.
- Structural PASS is NOT independently reviewed semantic admin-map coverage. I have NOT yet read/reviewed the new graph semantics, preservation or prior-flow changes. No graph accepted/merged.

Next coordinator should fetch this actual branch into an owned review clone, review exact generated artifacts, verify directed parent-map -> iframe -> GET/cargo -> service/repository -> Cargo data, actual all-cargo admin-map domain semantics, prior legitimate flows and baseline preservation (all non-source-graph files and all46 historical returns). Check actual proposal/current CI before authorized evidence landing. Use the existing830/46 baseline JSON below.

PR creation tool is scoped to the current source session repository/branch, not the pilot graph branch. Do not accidentally create a source PR. If using a CLI workflow for the pilot's existing graph branch, explicitly use the pilot repository/head/base; do not mutate the user-owned root checkout or redispatch generation.

## Slice discovery and actual user decisions

- Target task99: admin dashboard live map.
- Slice202: https://github.com/martins-vds/ai-factory-pilot-target/issues/202
- Actual Analyst203, ticketAM-02; original proposal204:
  https://github.com/martins-vds/ai-factory-pilot-target/pull/204
- Analyst finished head **25ec4b057be6a4b625f7d58b91cdd3f797562d04**, old baseD77. Its actual final-head CI42235350360 SUCCESS. It remains draft/open/unmerged, held for real graph repair/integration. DO NOT spawn a duplicate Analyst.
- It inventories11 pending capability ledger entries, source risk ranking/report, own return/journal/handoff. Initial baseline817 paths/44 returns all preserved. Three quirk drafts were published as real issues and removed from outbox by SAME Analyst.
- Its "unresolved rulings" wording predates the following actual human decisions and must be updated, not treated as a fresh user blocker.

Actual individual user choices, published and issues closed:

-205: **Use exact configured city coordinates**, no source random southwest offsets.
-206: **Show Unknown/unmapped cargo separately in an unmapped list with its real tracking link**; do not fabricate position or suppress valid markers.
-207: **Normalize accidental IN_PORT leading whitespace** to `In port`. Literal text divergence only; no claim that doubled visible spacing was observed.

Already approved architecture90/ADR0005: htmx polling a server-rendered markers partial using `CARGO_MAP_POLL_SECONDS`, default10; every state change visible next poll; drop source WebSocket/full reload/online-offline label.

After graph landing, resume SAME Analyst203/204 with actual main/new graphs and the three real rulings, preserve append-only history, update real counts/anchors/report, commit/push and finish. Independently review its final head/current CI before evidence-only merge. Then commission one actual Characterizer, then actual Planner. No implementation plan has been presented or approved and application implementation has NOT started.

## Source behavior facts to preserve/characterize

- Parent `admin/tracking/map.xhtml` embeds `#{request.contextPath}/admin/tracking/mapFrame.xhtml`.
- Frame fetches `/cargo-tracker/rest/cargo`; source JSON has seven fields: trackingId,routingStatus,misdirected,transportStatus,atDestination,origin,lastKnownLocation. NO destination.
- NOT_RECEIVED uses origin; other markers use lastKnownLocation.
- Source random offsets independently use `Math.floor((Math.random()*3)-3)` = -3,-2,-1 degrees per axis; target removal explicitly approved205.
- SentinelXXXXX becomesUnknown; dictionary has no Unknown position/name. Actual original browser consequence still needs characterization.
- Status precedence: NOT_ROUTED/MISROUTED -> misdirected -> atDestination -> transportStatus.
- Colors: NOT_ROUTEDgrey; MISROUTED/MISDIRECTED/UNKNOWNred; NOT_RECEIVEDgold; IN_PORT/ONBOARD_CARRIERgreen; AT_DESTINATION/CLAIMEDblack.
- Marker navigation opens detail in named window `winMap`; source hardcodeshttp/first path segment.
- Empty data builds base map without empty message; fetch/JSON failure only console-logs `cannot fetch cargos`.
- Do not conflate public single-cargo tracking or inspection notifications with the admin all-cargo map flow.
- Later acceptance must actually process/inspect handling, request the markers partial and assert changed location/status, and assert actual hx-trigger interval equals configured setting.

## Harness repairs completed during this slice

1. Source82/83: conservative real JSF iframe `contains` enrichment, independently reproduced before/after,46 parent enrichment tests and negative controls. Merged BDF/tree3dab; actual postmergeCI green. Normal pilot208/209 rollout merged35F; explicit parent installer and SAME actual Bootstrapper verifier. All prior accepted application evidence preserved.
2. Normal graph run42241735201 succeeded and generated branch367E, but still omitted admin-map domain flow. Parent independently verified iframe-to-Cargo code path fixed, yet held graph UNMERGED. Old branch **afs/graph-source-full-42241735201**, head367e987c44c55a2e954a8dd69a72397ad690b2d6. Do not merge or blindly rerun it.
3. Source84/85: reusable explicit requested-entrypoint domain generation and structural verifier, default behavior preserved. Initial candidate rejected for missing required tracing, direct-runner false success without domain, unsafe shared temporary filename. SAME original worker corrected all three. Parent44 coverage/tracing/bootstrap tests and actual finalE1CI42247847320 attempt2 SUCCESS. Merged9FC/tree db4D EXACT reviewedE1; actual source postmergeCI42249570559 SUCCESS.
4. Normal pilot210/211 rollout of9FC: original worker's archive acquisition SUCCEEDED and verified source content tree, but lacked Git HEAD required for honest bootstrap identity. Worker explicitly finished ownership handoff; parent used complete clean approved Git checkout and unchanged normal bootstrap. No fake Git metadata/manifest, offline/private skip, installed hotpatch or credentials transfer.
5. Parent actual install on original211branch at **9b21510ded472fa77121ca6d8760779ec29ca4c4**: exit0,108.13s,10agents/61skills, 77entries/389files/0problems, validation103/0. Exactly10 normal modified paths +1 new checker. All813 other baseline blobs/modes/all45 historical returns/four original worker outputs unchanged;65 direct source comparisons/all7 workflows equal approved generator.
6. First SAME-worker verification finished BLOCKED despite green CI: historical null-PR return validation after shallow history. Parent reproduced EXACT errors in fresh depth1 clone, then unchanged files passed103/0 after ordinary unshallow fetch. No old returns edited/gates waived/new source defect inferred. Resumed SAME worker with fresh full setup.
7. Final SAME worker actual17:09:13Z-17:19:38Z, head **1721ccdade84f4fbe3a3a3a0f1e82bbc11d6438c**, own return COMPLETE/independent_verification:true, parent installer explicitly named. Own real checks/provenance bounded honestly.
8. Parent final review proves all generated install bytes+two parent provenance files EXACT9B, all823 baseline paths match actual installation/all45 old returns unchanged, only four own worker files finalized, journal/handoff append-only. Final-head AFS42260550684/setup42260550645 SUCCESS. Accepted review6691642487; actual merge211 as5EE/tree19a EXACT reviewed. Issue210 closed/completed; main postmerge gates green.

Important lesson: `copilot_work_finished` means execution ended, NOT that the task succeeded. Read the actual own return/handoff. Green CI establishes neither role completion nor semantic coverage. I once briefly misreported verification as complete from lifecycle/CI and explicitly corrected it immediately upon reading the blocked return; no improper merge occurred.

## Previously completed work before this slice

- Actual L1 Slice Coordinator194/195 and L0 Program Orchestrator196/201 were validated/merged with independent review and actual postmerge gates.
- L1 CLI authentication was parent-assisted: parent executed unchanged installed read-only guards; SAME role independently interpreted/attributed results. Do not rewrite as autonomous worker CLI execution.
- L0 retrospective phase4 return dispatched nothing, identified frontier99/101/112 needing planning approval, preserved accepted113 and excluded172173.
- Earlier detailed checkpoints/session artifacts preserve this evidence. Do not rerun or overwrite historical acceptance to claim new slice acceptance.

## Local resources and operational boundaries

Artifacts directory:
`/home/vinima/.copilot/session-state/c53b1a7f22614cd4814a2ad82cbfa0a9/files/`

Key files/directories:

- `admin-live-map-before-focused-source-graph-inventory.json`: ACTUAL5EE/tree19a,830 paths/46 historical returns. Use for NEW5DF graph review.
- `admin-live-map-before-source-graph-inventory.json`: OLD35F,823/45. Not the new baseline.
- `pilot211-parent-bootstrap/`: independent complete owned pilot clone, currently detached1721; explicit origin/main5EE fetched. Clean after final verification; suitable for fetching new graph branch without touching user root checkout.
- `harness-domain-approved-source/`: independent complete clean approved9FC/tree db4D source, unchanged.
- `pilot204-admin-map-review/`: old original Analyst25EC review clone; old baseD77.
- `pilot211-parent-accepted-review.txt`, `pilot211-authorized-merge.json`, `verify-pilot211-install.py`.
- `pilot211-history-repro.log`: exact shallow103/2 -> full103/0 with no tracked changes. `pilot211-history-repro/`: owned full clone after reproduction.
- `harness85-parent-accepted-review.txt`, source merge/revision/test artifacts.
- Installed committed parent provenance: `.migration/evidence/HARNESS-ADMIN-LIVE-MAP-DOMAIN/parent-installation.md` and separate `.../runs/HARNESS-ADMIN-LIVE-MAP-DOMAIN-PARENT.md`.

User-owned root `/home/vinima/repos/ai-factory-swarm` has NOT been edited, branched, stashed, reset or pushed by this work. Do not confuse app metadata main with actual user branch. Use owned session clones/actual GitHub workers. Do not amend old commits. Include required Copilot coauthor in parent commits.

SQL session database contains `todos`, `todo_deps`, `orchestration_state`, `harness_findings` (27 findings). This database may not be shared with a replacement session; this file is the portable summary. Current substantive state: two source fixes and both rollouts done; graph generation completed structurally but independent review pending; understanding integration in progress; characterization/planning/approval/implementation/acceptance pending.

Existing read-only progress monitor: desktop session `ea3e24a4-bedc-49c8-8be8-f8099b4e9467`, name Swarm progress monitor. Intended five-minute checks; scheduling health/cadence has NOT been independently verified and it was observed non-running/activityunknown. Do not claim healthy automatic follow-through, create a duplicate monitor, or give it mutation/merge/dispatch authority. Last instructions watched graph42274481680. New coordinator should transfer the relevant watch only if needed.

Only actual platform `copilot_work_started`/`copilot_work_finished` establishes lifecycle. Assignment/PR creation is not start; finish is not successful return; CI is exact-head only. Do not busy-poll long AI workflows or blindly retry uncertain dispatch. Current graph workflow is COMPLETED, branch exists and no PR exists; no new run is necessary.
