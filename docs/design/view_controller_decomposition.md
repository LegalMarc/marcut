# Design Spike: Decomposing SettingsView.swift and DocumentRedactionViewModel.swift

Status: Design spike (no code changes). Companion to issue #24. Prereq 1
(#97 -- `PermissionManager` safe under `swift test`) is done: constructing
`SettingsView` and calling `DocumentRedactionViewModel.processAllDocuments`
no longer aborts the test process. The two references below to that crash
risk are now historical; see the note after each. Prereq 2 (#98) is also
done: `DocumentRedactionViewModel`'s dependency on the embedded Python
runner, the Ollama bridge, and the share sheet is now injectable
(`RedactionRunning.swift`, `runnerProvider`, `llmPreflightCheck`,
`modelReadinessCheck`, `sharePresenter`), with zero behavior change, so a
recording fake can stand in for `PythonKitRunner` in the golden harness
(#100). Prereq 3 (#99) is also done: `DocumentRedactionViewModel.init`,
`SettingsView.init`, and `MetadataCleaningSettings.load()`/`save()` now
accept an injected `UserDefaults` suite (default `.standard`, every
production call site unchanged), and every §3.2 characterization target
listed in #99 is widened from `private` to `internal`, so tests can seed
preference state and stored ETA/batch properties without touching real
`UserDefaults.standard` or reaching for reflection. Prereq 4 (#100) is also
done: `Tests/MarcutAppTests/RecordingRedactionRunner.swift`,
`RedactionCharacterizationHarness.swift`, and
`RedactionCharacterizationTests.swift` add a scripted `RedactionRunning`
fake plus a golden-snapshot harness (20 scenarios under
`Tests/MarcutAppTests/Golden/`) pinning exactly what the view model hands
the Python runner -- method, arguments, and the nine-key `MARCUT_*`
environment allowlist at the moment of the call -- and the resulting
item/flag/environment state afterward. Every extraction slice below
(#103-#111) must run
`swift test --package-path src/swift/MarcutApp --filter RedactionCharacterizationTests`
before and after its change and get zero golden diffs; the harness's own
header doc-comment (in `RedactionCharacterizationHarness.swift`) is the
canonical description of what is snapshotted and how to re-baseline.
Prereq 5 (#101) is also done for six of its seven targets:
`Tests/MarcutAppTests/ViewModelCharacterizationTests.swift` adds direct-call
characterization tests for `updateState()` (incl. the power-assertion
begin/end edge and `PendingBatchJobStore` persistence/dedupe), the batch ETA
math, `applyOutputArtifacts`, `shareFinalRedactedCopy`'s environment
save/restore, the `environmentStatus`/`isEnvironmentReady` diagnostics
matrix, and pending-job recovery (`resumePendingJob`/`discardPendingJob`).
The seventh target, progress mapping (`mapPhaseToStage`/`extractChunkInfo`/
`applyPythonKitProgress`), remains untested: those three live inside a
`private extension DocumentRedactionViewModel` block that #99's widening
pass did not cover, so `@testable import MarcutApp` cannot reach them from a
different file. A follow-up, visibility-only ticket (same shape as #99 --
widen that one extension from `private extension` to `extension`, no other
edit) is needed before that slice's characterization test can be added; see
`ViewModelCharacterizationTests.swift`'s header for the full note. The two
reimplemented-logic tests `updateState()`'s coverage used to rely on
(`MarcutAppTests.swift`, formerly `testFinishedProcessingStateLogic`/
`testProcessingStateLogic`, plus the unrelated `testPreparingStateLogic`
dead test) are removed now that real coverage exists. Prereq 6 (#102) is
also done: `Tests/MarcutAppTests/AdvancedModeDefaultsMigrationTests.swift`
pins `SettingsView.init`'s and
`DocumentRedactionViewModel.applyAdvancedModeDefaultsIfNeeded()`'s
`UserDefaults` seeding across the eight start states x three call orders in
#102's scope, plus two named tests for the two drift points below (only
`SettingsView.init` seeds `outputSaveLocationPreference` and
`unsavedReportQuitBehavior`). This is tests only -- the drift is pinned, not
resolved; #106 must still decide, on the record, whether the unified
migrator keeps seeding those two keys.

## Goal

`SettingsView.swift` (1,987 lines) and `DocumentRedactionViewModel.swift`
(2,926 lines) — both larger today than the 1,700/2,760 line counts cited when
this ticket was filed — are the two largest files in the Swift app and mix
several unrelated responsibilities each. This doc inventories those
responsibilities, proposes a target structure with clear component
boundaries, and — because this app performs legal-document redaction, where
an accidental behavior change during extraction is a correctness/privacy
risk and not just a code-quality one — lays out a concrete plan for proving
zero behavior change before, during, and after each extraction. This ticket
produces the design only; it does not touch either file.

## Why this is a design spike, not a direct refactor

`DocumentRedactionViewModel` is `@MainActor`, holds all `@Published` UI
state, and is the single call site for the PythonKit bridge that actually
redacts documents. Its methods are entangled by shared mutable state
(`processingTasks`, `batchProcessingStartTimes`, `items`) and by environment
variables set as side effects (`applyAdvancedSettingsEnvironment()`,
`applyMetadataSettingsEnvironment()`) that a later method silently depends
on. Today's test suite
(`src/swift/MarcutApp/Tests/MarcutAppTests/MarcutAppTests.swift`) explicitly
avoided instantiating `SettingsView` for rendering
(comment at line 469: "A view-rendering test that instantiates `SettingsView`
… `SettingsView` transitively initializes `PermissionManager.shared`") --
now fixed by #97: `SettingsView` construction and `processAllDocuments` are
both exercised directly (`testSettingsViewConstructsWithoutCrashingUnderSwiftTest`,
`testProcessAllDocumentsWithNoItemsCompletesWithoutCrashing`); a full
`NSHostingView` render to assert on-screen elements is still out of reach,
but for an unrelated reason (no `.app` bundle/Xcode project in this repo's
build, so there is no way to visually confirm rendered output either way) --
and covers `DocumentRedactionViewModel` only through a handful of pure static
helpers (`finalRedactedCopyURL`, `makeSensitiveReportFilePrivate`) plus
`updateState()`'s boolean-flag logic reimplemented inline in test code
(line 130: "This matches the logic in `DocumentRedactionViewModel
.updateState()`" — a duplicated copy, not a call into the real method).
There is no characterization-test harness pinning current end-to-end
behavior. An unattended mechanical split of either file risks silently
changing which documents get redacted, how errors surface, or what gets
persisted across a crash — so this ticket stops at the plan.

---

## 1. Responsibility Inventory

### 1.1 `SettingsView.swift` (1,987 lines)

| Responsibility | Evidence (functions/properties) | Approx. lines |
|---|---|---|
| **Search/filter infrastructure** | `SettingsSection` enum, `sectionLabels` static table, `matchesSearch(_:query:)`, `isSectionVisible(_:)`, `isRuleVisible(_:)` | 81–158 (~78) |
| **UserDefaults migration/seeding in `init`** | The `init(viewModel:)` body seeds `advancedModeEnabled`, `advancedAIMode`, `advancedLLMConfidence`, the one-time `advancedLLMConfidenceMigratedTo99` 95→99 migration, `outputSaveLocationPreference` (with legacy-key fallback), `unsavedReportQuitBehavior`, then resolves `initialSettings.mode`/`llmConfidenceThreshold` from those defaults | 160–215 (~55) |
| **Section view builders (UI layout)** | `processingModeSection`, `sharedSettingsSection`, `rulesEngineSection`, `aiModelSection`, `advancedAISection`, `debugSection`, `headerView`, `footerButtons` | 308–1005 (~700) |
| **Timeout slider math** | `timeoutSteps`, `timeoutDisplay`, `timeoutSliderIndex` (non-linear step table + display formatting) | 787–826 (~40) |
| **Settings-profile export/import (file I/O)** | `exportSettingsProfile()`, `importSettingsProfile()` — `NSSavePanel`/`NSOpenPanel`, security-scoped resource access, `RedactionProfile` encode/decode | 1043–1107 (~65) |
| **Excluded-words / system-prompt override editing** | `openExcludedWordsEditor`, `saveExcludedWords`, `resetExcludedWordsToDefault`, `cancelExcludedWordsEditing`, `restoreExcludedWordsDefaults` and the system-prompt equivalents; backed by `UserOverridesManager.shared` | 1207–1281 (~75) |
| **Mode/rule selection business logic** | `binding(for:)`, `invertRuleSelection`, `selectRulesOnly`, `selectRulesPlusAI`, `applyAdvancedModeSelection`, `selectAdvancedAIMode`, `advancedModeTitle` — mirrors and re-derives logic that also lives in `DocumentRedactionViewModel.applyAdvancedModeDefaultsIfNeeded()` | 1144–1205 (~60) |
| **`OverrideEditorSheet` (private view)** | Generic text-editor sheet reused by excluded-words and system-prompt editors | 1284–1340 |
| **`ExcludedWordMatchPreview` (private view)** | Live "test a phrase" preview wired to `ExcludedWordMatcher` (a port of the Python rule) | 1346–1419 |
| **`ScrollableTextEditor` (private `NSViewRepresentable`)** | AppKit `NSTextView` wrapper | 1421–1474 |
| **`FirstRunSetupView` (separate top-level view)** | Full onboarding/model-download wizard: `welcomeContent`, `modelSelectionContent`, `downloadingContent`, `completeContent`, `handleNextButton`, `downloadModel`, `cancelDownload`, `closeSetup`, `completeRulesOnly` | 1476–1839 (~365) |
| **`FeatureRow`, `ModelSelectionRow` (shared display components)** | Reused by both `SettingsView`'s AI Model section and `FirstRunSetupView` | 1841–1987 (~145) |

Observation: `SettingsView` is really **four files' worth of content** —
(a) the settings form itself, (b) two generic reusable sheet/editor
components, (c) an entirely separate first-run onboarding flow that happens
to share `ModelSelectionRow`, and (d) UserDefaults-migration logic that
duplicates what `DocumentRedactionViewModel.applyAdvancedModeDefaultsIfNeeded()`
already does at app-launch time (both read/write the same `DefaultsKey`
constants independently — see `DocumentRedactionViewModel.swift:1978–2013`
vs. `SettingsView.swift:160–215`).

### 1.2 `DocumentRedactionViewModel.swift` (2,926 lines)

| Responsibility | Evidence (functions) | Approx. lines |
|---|---|---|
| **Published UI state** | `items`, `hasDocuments`, `hasValidDocuments`, `hasProcessingDocuments`, `hasCompletedDocuments`, `hasFinishedProcessing`, `hasFailedDocuments`, `metadataReportErrorMessage`, `reportErrorMessage`, `settings`, `frameworkAvailable`, `shouldShowFirstRunSetup`, `isPythonInitializing`, `pythonInitializationError`, `batchETA`, `pendingResumeRecord`, `firstRunEntryPoint` | 52–195 |
| **Python-runtime lifecycle** | `init()`'s `pythonRunnerReady`/`pythonRunnerFailed` observers, `pythonInitObservers`, `deinit` cleanup | 96–171 |
| **Document management (add/remove/validate)** | `add(urls:)`, `checkDocument(_:)`, `clearAllDocuments()`, `removeDocument(_:)`, `validateDestination(_:)` | 215–292, 1505–1537, 2421–2433 |
| **Batch coordination** | `processAllDocuments(to:includeRetryItems:)`, `needsRedaction(_:includeRetryItems:)`, `stopProcessing()`, `retryDocument`, `retryFailedDocuments`, `retryFailedDocumentsHandler` | 295–403, 1323–1419, 1422–1430 |
| **Metadata-only scrub flow** | `scrubMetadataOnly`, `scrubDocumentMetadataOnly`, `generateMetadataReportsInPlace`, `generateMetadataReport`, `generateScrubHTMLIfMissing` | 407–623, 783–949, 2434–2501 |
| **Output-directory / permission resolution** | `resolveOutputDirectory`, `resolveTemporaryReportDirectory`, `outputSaveLocationPreference`, `outputLocationErrorMessage`, `setOutputAccessError`, `requestMetadataOutputAccess`, `retryFileAccessPermissions(for:)`, `retryFileAccessPermissionsFromBanner` | 656–777, 690–727 |
| **Metadata-report error state** | `metadataReportErrorPayload`, `setMetadataReportError`, `setReportError`, `metadataReportPermissionMessage`, `clearMetadataReportError(s)`, `clearReportError` | 624–782 |
| **Single-document process execution** | `processDocument(_:destination:)`, `processDocumentWithPythonKit`, `logAdvancedSettingsSnapshot`, `applyAdvancedSettingsEnvironment`, `applyMetadataSettingsEnvironment`, `applyOutputArtifacts`, `awaitPythonOutcome` | 950–1322 (~370) |
| **Progress/heartbeat monitoring** | `ensureHeartbeatMonitorRunning`, `applyPythonKitProgress`, `mapPhaseToStage`, `extractChunkInfo`, `heartbeatTasks`, `heartbeatTimeout` | 2502–2603 |
| **Batch ETA estimation** | `batchProcessingStartTimes`, `batchETASamples`, `recordBatchETASample`, `updateBatchETA`, `documentSizeSignal` — depends on `BatchETASample`/`BatchETACalculator` (external) | 2064–2104 |
| **Pending-job crash recovery** | `pendingBatchJobPaths`, `persistPendingBatchJobIfNeeded`, `resumePendingJob`, `discardPendingJob`, `didJustResumePendingJob`, `lastPersistedPendingPaths` (interacts with `PendingBatchJobStore`, external) | 1450–1505 |
| **Share/export flow** | `openRedactedDocument`, `shareDocument`, `confirmAndShareReviewCopy`, `shareFinalRedactedCopy`, `presentSharePicker`, `restoreEnvironmentValue` | 1540–1656 |
| **Report viewing/saving** | `openReport`, `openScrubReport`, `openMetadataReport`, `presentReport`, `resolvedHTMLURL`, `saveMetadataReport`, `saveMetadataReportToDownloads`, `saveMetadataReportToDirectory`, `exportMetadataReport`, `revealInFinder` | 1658–1963 (~305) |
| **Settings persistence/defaults** | `updateSettings(_:)`, `applyAdvancedModeDefaultsIfNeeded`, `initializeDebugSync`, `requestFirstRunSetup`, `clearLogs`, `resetFirstRunEntryPoint` | 1966–2038 |
| **State-flag aggregation** | `updateState()`, `finalizeProcessing(for:)`, `assignFailureMessageIfNeeded`, `loadFailureReport(at:)` | 1432–1445, 2040–2153 |
| **Environment/diagnostics status** | `isEnvironmentReady`, `getOllamaPath`, `environmentStatus`, `attemptEnvironmentRecovery`, `getDetailedEnvironmentDiagnostics`, `checkEnvironment`, `refreshEnvironmentStatus`, `ollamaRunning`, `availableModels`, `installedModelCount`, `shouldSuppressModelSetupPrompt`, `downloadModel`, `cancelModelDownload` | 2156–2418 (~260) |
| **DOCX post-write validation** | `validateDocxStructure(at:)` | 2607+ |
| **Static, side-effect-free helpers (already decoupled)** | `finalRedactedCopyURL(for:fileExists:)`, `makeSensitiveReportFilePrivate(_:)`, `normalizeModelIdentifier(_:)` | 12–51 |

Observation: this file is doing the job of at minimum five collaborators —
a batch orchestrator, a single-document process runner, a heartbeat/ETA
monitor, an output/report file manager, and an environment/diagnostics
service — glued together by `@MainActor` state and read implicitly by
almost every method (e.g. `settings`, `items`, `processingTasks`).

---

## 2. Proposed Target Structure

Principle: extract **collaborators owned by the view model**, not new
independent view models — `DocumentRedactionViewModel` stays the single
`@Published`/`@MainActor` source of truth the views bind to, so SwiftUI
diffing and existing `@ObservedObject` call sites are untouched. Extracted
types take what they need as constructor parameters/closures and return
results; they do not reach back into the view model.

### 2.1 `DocumentRedactionViewModel.swift` split

```
DocumentRedactionViewModel (stays, ~400–500 lines)
├── owns: @Published state, `items`, `settings`
├── delegates batch orchestration → BatchCoordinator
├── delegates single-doc execution → ProcessRunner
├── delegates heartbeat/ETA → ProgressMonitor
├── delegates output file resolution/report I/O → OutputArtifactManager
├── delegates share/export → DocumentShareService
└── delegates environment/model diagnostics → EnvironmentDiagnosticsService (mostly a thin
    wrapper already — pythonBridge/AppDelegate.pythonRunner do the real work)
```

- **`BatchCoordinator`** — owns `processAllDocuments`, `scrubMetadataOnly`,
  `generateMetadataReportsInPlace`, `needsRedaction`, `stopProcessing`,
  `retryDocument`/`retryFailedDocuments`, `processingTasks`. Boundary: takes
  an array of `DocumentItem` plus a `ProcessRunner` (or a closure
  `(DocumentItem, URL) async -> Void`) and a way to resolve output
  directories; reports completion back via a delegate callback or
  `AsyncStream` the view model subscribes to, rather than mutating
  `@Published` state directly (keeps it host-agnostic for tests). This
  is the piece most entangled with `Task` cancellation and the pending-job
  persistence path, so it is also the highest-risk piece — see §4.

- **`ProcessRunner`** — owns `processDocument`, `processDocumentWithPythonKit`,
  `applyAdvancedSettingsEnvironment`, `applyMetadataSettingsEnvironment`,
  `logAdvancedSettingsSnapshot`, `awaitPythonOutcome`. Boundary: takes a
  `DocumentItem`, a destination `URL`, `RedactionSettings`, and the
  `PythonKitRunner`; returns a result type (success/failure + output paths)
  instead of mutating `item.status` inline, so behavior is testable without
  a live PythonKit runner (inject a protocol-typed runner).

- **`ProgressMonitor`** (heartbeat + ETA, currently two loosely related
  concerns under one `// MARK:` each) — owns `ensureHeartbeatMonitorRunning`,
  `applyPythonKitProgress`, `mapPhaseToStage`, `extractChunkInfo`,
  `recordBatchETASample`, `updateBatchETA`, `documentSizeSignal`,
  `heartbeatTasks`, `batchProcessingStartTimes`, `batchETASamples`. Pure
  enough (`mapPhaseToStage`, `extractChunkInfo`, ETA math) to unit test today
  without extraction — good first slice (§4).

- **`OutputArtifactManager`** — owns `applyOutputArtifacts`,
  `resolveOutputDirectory`, `resolveTemporaryReportDirectory`,
  `findScrubReport`-style lookups, `openReport`/`openScrubReport`/
  `openMetadataReport`/`presentReport`/`resolvedHTMLURL`,
  `saveMetadataReport` and its `ToDownloads`/`ToDirectory` helpers,
  `exportMetadataReport`, `revealInFinder`, plus the metadata-report error
  payload helpers (`metadataReportErrorPayload`, `setMetadataReportError`,
  `metadataReportPermissionMessage`). This is the largest extractable block
  (~500+ lines) and the most mechanical — mostly `FileManager`/`NSWorkspace`
  calls keyed off `DocumentItem` URL properties.

- **`DocumentShareService`** — owns `shareDocument`,
  `confirmAndShareReviewCopy`, `shareFinalRedactedCopy`, `presentSharePicker`,
  `restoreEnvironmentValue`, `openRedactedDocument`. Small, self-contained,
  and already reads like a service (constructs its own `NSAlert`s). Good
  second slice.

- **`EnvironmentDiagnosticsService`** — owns `isEnvironmentReady`,
  `environmentStatus`, `attemptEnvironmentRecovery`,
  `getDetailedEnvironmentDiagnostics`, `checkEnvironment`,
  `refreshEnvironmentStatus`, `ollamaRunning`, `availableModels`,
  `installedModelCount`, `shouldSuppressModelSetupPrompt`, `downloadModel`,
  `cancelModelDownload`, `getOllamaPath`. Mostly forwards to
  `pythonBridge`/`AppDelegate.pythonRunner` already — lowest behavior risk,
  good candidate for an early slice alongside `ProgressMonitor`.

- **Stays on `DocumentRedactionViewModel` directly**: `add(urls:)`,
  `checkDocument`, `clearAllDocuments`, `removeDocument`, `updateState`,
  `finalizeProcessing`, `assignFailureMessageIfNeeded`, pending-job
  persistence (`persistPendingBatchJobIfNeeded`, `resumePendingJob`,
  `discardPendingJob`), `updateSettings`,
  `applyAdvancedModeDefaultsIfNeeded`, `validateDocxStructure`. These are
  either core state-machine transitions that every collaborator needs to
  trigger, or small enough (and load-bearing enough for crash-recovery
  correctness) that extracting them adds indirection without reducing risk.

### 2.2 `SettingsView.swift` split

```
SettingsView.swift (2,136 lines: form layout + search)
├── AppTheme.swift — done (#103): moved, no logic change
├── SettingsProfileIO.swift — done (#108): exportSettingsProfile/importSettingsProfile
│   moved verbatim, with panel presentation made injectable (`presentSavePanel`/
│   `presentOpenPanel` closures defaulting to a real NSSavePanel/NSOpenPanel) so the
│   encode/write and read/decode paths are testable without driving a modal panel;
│   SettingsView keeps localSettings/metadataSettings/profileErrorMessage/
│   profileImportSucceeded since they're core view state read elsewhere too
├── SettingsOverridesController.swift — done (#108): excluded-words and system-prompt
│   open/save/cancel/restore functions plus their draft/baseline/flag state moved into
│   an `ObservableObject`, backed by UserOverridesManager.shared (already a singleton
│   service — this mostly moved @State-driven glue code, not logic); SettingsView binds
│   to it via `@StateObject` since (unlike the view-model collaborators in §2.1, which
│   keep @Published state on DocumentRedactionViewModel) SettingsView has no separate
│   model object of its own to hold that state
├── AdvancedModeDefaultsMigrator (NEW, shared) — the UserDefaults
│   seeding/migration block from SettingsView.init AND
│   DocumentRedactionViewModel.applyAdvancedModeDefaultsIfNeeded, unified
│   into one function both call, removing today's duplication
├── OverrideEditorSheet.swift — done (#103): moved, no logic change
├── ExcludedWordMatchPreview.swift — done (#103): moved, no logic change
├── ScrollableTextEditor.swift — done (#103): moved, no logic change
├── ModelSelectionRow.swift — done (#103): moved, no logic change (shared by
│   SettingsView and FirstRunSetupView)
├── FeatureRow.swift — done (#103): moved, no logic change (used only by
│   FirstRunSetupView but tiny/generic)
└── FirstRunSetupView.swift — done (#103): moved, no logic change; the
    entire onboarding wizard was already a distinct `View` with no reach
    into SettingsView's private state
```

The `SettingsView` split is materially lower-risk than the view model split:
most of the boundaries above are already-separate `struct`s or
`private func` groups with no shared mutable state beyond `@State` that
stays local to the file being moved. The one genuine cross-cutting risk is
`AdvancedModeDefaultsMigrator`: today `SettingsView.init` and
`DocumentRedactionViewModel.applyAdvancedModeDefaultsIfNeeded()` each
independently read/seed the same `DefaultsKey` values on every
view-construction / view-model-init, and they are not byte-for-byte
identical (`SettingsView.init` additionally seeds
`outputSaveLocationPreference` and `unsavedReportQuitBehavior`, which
`applyAdvancedModeDefaultsIfNeeded` does not touch). Unifying them is
valuable (it is the actual duplication `backlog.md` flags) but must be its
own slice with characterization tests proving both call sites still end up
with identical `UserDefaults` state afterward — see §4, Slice 5.

---

## 3. Behavior-Parity Verification Plan

### 3.1 What existing tests already cover

From `src/swift/MarcutApp/Tests/MarcutAppTests/MarcutAppTests.swift`:

- `SettingsView.matchesSearch(_:query:)` — direct unit coverage (lines
  454–466).
- `DocumentRedactionViewModel.finalRedactedCopyURL(for:fileExists:)` and
  `.makeSensitiveReportFilePrivate(_:)` — direct unit coverage via the
  static/injectable-closure variants (lines 303, 316, 328).
- `updateState()`'s flag-derivation logic — covered only by a **reimplementation**
  of the same boolean logic inline in the test file (line 130 comment: "This
  matches the logic in `DocumentRedactionViewModel.updateState()`"), which
  means the test currently protects against drift in the test author's
  understanding, not against drift in the real method. This is a gap, not
  coverage, and should be closed before `updateState()`-adjacent code moves
  (it will not move in the slices proposed here, but `finalizeProcessing`
  and `assignFailureMessageIfNeeded`, which call it, might in a later PR).
- Pending-batch-job persistence — exercised indirectly around line 1070
  against `PendingBatchJobStore`, not against
  `DocumentRedactionViewModel` directly.
- No test instantiates `SettingsView` or `FirstRunSetupView` for a full
  `NSHostingView` render. Plain construction is no longer unsafe (#97 guards
  `PermissionManager.shared`'s `UNUserNotificationCenter` access), but this
  repo has no `.app` bundle/Xcode project to render against, so on-screen
  assertions (e.g. an `NSSearchField` being present) remain out of reach.
- No test exercises `processDocument`, `processDocumentWithPythonKit`,
  `shareDocument`, `applyOutputArtifacts`, or any of the report-saving
  methods — these require a live (or mocked) `PythonKitRunner` and touch
  the filesystem/`NSWorkspace`/`NSSavePanel`, none of which the current
  suite mocks.

### 3.2 Characterization tests needed *before* any extraction

For each component slated to move (§2), pin today's behavior first, using
today's file layout (no extraction yet) so the tests can be written and
merged independently of any refactor PR:

1. **`updateState()` — replace the reimplemented-logic test with a real
   call.** Construct a `DocumentRedactionViewModel`, populate `items` with
   `DocumentItem`s in each `DocumentStatus` (`validDocument`, `.processing`,
   `.completed`, `.failed`, pending-review, retryable), call the paths that
   trigger `updateState()` (e.g. via `add(urls:)` / direct status mutation +
   a public trigger, adding a `@testable import` internal-visibility shim if
   `updateState()` needs to become `internal` instead of `private` for the
   test target — a zero-behavior-change visibility widening), and assert on
   the resulting `@Published` flags. This closes the existing coverage gap
   and becomes the regression test for `BatchCoordinator`'s eventual home
   for this logic.

2. **`mapPhaseToStage` / `extractChunkInfo` (ProgressMonitor candidate)** —
   both look like pure functions taking a phase identifier / progress
   update and returning a value. Table-test every `ProcessingStage` /
   `PythonRunnerProgressUpdate` shape currently handled, including
   `isEnhancedMode` true/false branches, before moving them.

3. **ETA math (`recordBatchETASample`, `updateBatchETA`,
   `documentSizeSignal`)** — feed a scripted sequence of document
   completions with known durations/sizes and assert the resulting
   `batchETA` sequence, including the "fewer than `BatchETACalculator
   .minimumSamples`" `nil` case called out in the doc comment at line 71.

4. **`applyOutputArtifacts`** — given a `DocumentItem` and a directory
   pre-populated with report/scrub-report files in the exact naming
   patterns `processDocument` constructs (including the "alternate path"
   fallback via `findScrubReport`), assert every `item.*OutputURL` and
   `*HTMLOutputURL` property ends up set (or nil) correctly. This is pure
   filesystem-in/state-out and testable with a `TemporaryDirectory` fixture
   without touching PythonKit.

5. **`AdvancedModeDefaultsMigrator` unification (highest-value, must be
   characterized first)** — **done (#102)**: snapshot `UserDefaults` state
   after `SettingsView.init` alone, after `DocumentRedactionViewModel
   .applyAdvancedModeDefaultsIfNeeded()` alone, and after both run in the
   app's actual startup order, across the matrix of {defaults empty,
   defaults from a pre-0.x install with only the legacy
   `legacyMetadataReportAlwaysSaveToDownloads` key, defaults already fully
   migrated, the one-time confidence-95-to-99 migration flag already
   consumed vs. not, `advancedModeEnabled == false` with `hasCompletedFirstRun`
   true and false} — see `Tests/MarcutAppTests/AdvancedModeDefaultsMigrationTests.swift`.
   Only once this matrix is pinned should the two
   call sites be merged into one shared migrator — this is the single
   riskiest de-duplication in this doc because it is real logic
   duplication (not just organizational), so unifying it can change what
   gets written to `UserDefaults` on first launch after an update if the
   two versions have actually drifted (per §2.2, they already have:
   `outputSaveLocationPreference`/`unsavedReportQuitBehavior` seeding is
   only in `SettingsView.init` today — now pinned as two named tests, not
   resolved). #106 does the actual unification.

6. **`shareDocument` / `shareFinalRedactedCopy` environment-variable
   save/restore** — assert that `MARCUT_METADATA_PRESET`,
   `MARCUT_METADATA_ARGS`, and `MARCUT_METADATA_SETTINGS_JSON` are restored
   to their pre-call values (including "was unset" → stays unset) after
   `shareFinalRedactedCopy` runs, both on success and on the runner-error
   path. This is exactly the kind of side-effecting-global-state code that
   is easy to subtly break during extraction (e.g. an early `return` added
   during refactor skipping the `defer` block's semantic equivalent).

Where a target method is `private` and has no test seam, the minimal,
behavior-neutral prerequisite is to widen its access to `internal` (never
`public`) so `@testable import MarcutApp` can reach it — this is itself a
small, low-risk, separately-landable change that should go in *before* the
characterization tests that need it, reviewed on its own as "no logic
change, visibility only."

### 3.3 How each extraction PR proves no behavior changed

For every slice in §4:

1. **Land characterization tests first**, against the pre-extraction code,
   in their own PR. CI green here is the baseline.
2. **Extraction PR moves code only** — no logic edits beyond what's
   mechanically required to satisfy Swift's access rules (e.g. a method
   becoming `internal` on the new type instead of `private` on the old
   one) and updating call sites to go through the new collaborator instead
   of `self`. Reviewer diffs the moved method body against its old body
   with `git diff --color-moved` (or manual side-by-side) to confirm no
   incidental changes rode along.
3. **Same characterization tests run unmodified against the extracted
   code** (only their setup changes, e.g. constructing a
   `BatchCoordinator` instead of a `DocumentRedactionViewModel` and calling
   through it) and must pass without edits to their assertions. A test
   assertion needing to change to keep passing is a signal the extraction
   changed behavior, not just location, and should block the PR.
4. **`swift build` + `swift test` both green**, plus the full green-gate
   this repo already requires
   (`PYTHONPATH=src/python python3 -m pytest -q && swift build
   --package-path src/swift/MarcutApp && swift test --package-path
   src/swift/MarcutApp`) — the Python suite is included because several
   of these methods (`processDocumentWithPythonKit`,
   `applyAdvancedSettingsEnvironment`, `applyMetadataSettingsEnvironment`)
   set environment variables the Python pipeline reads, and an extraction
   that reorders when those are set relative to the PythonKit call could
   break Python-side behavior with no Swift-test signal at all.
5. **One manual end-to-end smoke run per slice** (per this repo's existing
   `marcut redact --enhanced --debug` CLI flow or the packaged app) against
   a sample file from `sample-files/`, comparing the produced `.docx` +
   `_report.json` byte-for-byte (or diff-reviewed) against a
   pre-extraction run on the same input/settings/seed. This is the one
   check that covers the PythonKit boundary itself, which unit tests can't
   reach without a live runner.
6. **No PR combines an extraction with a behavior change.** If a bug is
   found mid-extraction, land the bug fix separately (before or after) so
   the extraction PR's diff is provably behavior-preserving on its own.

---

## 4. Recommended Extraction Order

Ordered smallest/lowest-risk first; each slice is separately landable and
scoped to roughly 10 files or fewer, per this repo's workflow-loop
conventions. Slices 1–3 require no characterization tests beyond what they
add themselves (their targets are already pure or nearly pure); slices 4+
depend on the characterization tests from §3.2 landing first.

1. **File-only moves, zero logic risk** — **done (#103)**: extracted
   `AppTheme`, `OverrideEditorSheet`, `ExcludedWordMatchPreview`,
   `ScrollableTextEditor`, `FeatureRow`, and `ModelSelectionRow` out of
   `SettingsView.swift` into their own files (no code changes beyond the
   `private struct` → `struct` access widening the ticket's own extraction
   rules require for `OverrideEditorSheet`, `ExcludedWordMatchPreview`, and
   `ScrollableTextEditor`, now used cross-file). `swift build` + `swift test`
   green, zero golden diffs, no test assertions changed.

2. **`FirstRunSetupView` → its own file** — **done (#103)**, merged into
   the same PR as slice 1 per that issue's scope (both are pure file
   moves): the onboarding wizard moved unchanged into
   `FirstRunSetupView.swift`. Verification: same as above. The manual
   click-through of the onboarding flow (welcome → model selection →
   download → complete) is deferred to the next release's smoke check per
   #103's notes, since it has no automated coverage today per §3.1.

3. **`ProgressMonitor` extraction** — **done (#104)**: heartbeat/stall
   watchdog (`ensureHeartbeatMonitorRunning`, `failStalledDocument`) and
   batch-ETA estimation (`recordBatchETASample`, `updateBatchETA`,
   `documentSizeSignal`), plus progress mapping (`applyPythonKitProgress`,
   `mapPhaseToStage`, `extractChunkInfo`) — these were the most
   nearly-pure functions in `DocumentRedactionViewModel` — moved into a
   `ProgressMonitor` type owned by the view model via constructor closures
   (an items snapshot, `hasProcessingDocuments`, a "fail this item"
   callback, and a `batchETA` sink), so the collaborator never reaches
   back into the view model. `activeAttemptTokens` stays on the view model
   until #111 per the issue's own note. Progress-mapping's `private
   extension` visibility gap (blocking `@testable import` coverage,
   flagged in `ViewModelCharacterizationTests.swift`) was incidentally
   resolved by the move: those methods are now ordinary internal instance
   methods on `ProgressMonitor`. Verification per §3.3: `swift build` +
   `swift test` green, zero golden diffs, #101's ETA characterization
   tests pass with call sites routed through `viewModel.progressMonitor`
   (construction-only changes, no assertions changed).

4. **`EnvironmentDiagnosticsService` extraction** — **done (#105)**:
   `isEnvironmentReady`, `environmentStatus`, `attemptEnvironmentRecovery`,
   `getDetailedEnvironmentDiagnostics`, `checkEnvironment`,
   `refreshEnvironmentStatus`'s core refresh computation, `ollamaRunning`,
   `availableModels`, `installedModelCount`, `shouldSuppressModelSetupPrompt`,
   `downloadModel`, `cancelModelDownload`, and `getOllamaPath` moved into an
   `EnvironmentDiagnosticsService` collaborator that takes `pythonBridge` and
   a runner-provider closure at construction and returns values from every
   method rather than reaching back into the view model. The
   Python-initialization wait loop and the first-run-prompt decision tree
   inside `refreshEnvironmentStatus(triggerFirstRunCheck:)` stayed on the
   view model per this slice's own scope note (they depend on
   `isPythonInitializing`/`hasCompletedFirstRun`/`markFirstRunComplete`,
   view-model concerns unrelated to environment diagnostics); the view model
   applies the collaborator's `RefreshOutcome`/`RecoveryOutcome` return
   values to its own `@Published` `frameworkAvailable`/
   `shouldShowFirstRunSetup`/`firstRunEntryPoint` and to `settings.model`.
   #101's diagnostics-matrix characterization tests
   (`ViewModelCharacterizationTests.swift`, §4 slice-4 diagnostics matrix)
   pass unmodified against the extracted code, construction-only unchanged.
   Verification per §3.3: `swift build` + `swift test` green, SwiftFormat
   lint clean, zero golden diffs.

5. **`AdvancedModeDefaultsMigrator` unification** — the highest-value and
   highest-risk de-duplication (§2.2, §3.2 item 5). Characterization tests
   must land and pass against *both* existing call sites first; the
   unification PR should keep the merged function's parameters explicit
   enough (e.g. `hasCompletedFirstRun: Bool`, `seedModeIfLLM: RedactionMode?`)
   that `SettingsView.init` and
   `DocumentRedactionViewModel.applyAdvancedModeDefaultsIfNeeded()` can both
   call the same function and produce identical `UserDefaults` state to
   today, including `SettingsView.init`'s extra
   `outputSaveLocationPreference`/`unsavedReportQuitBehavior` seeding
   (which the migrator must also cover, or those two keys must be
   explicitly and separately documented as staying in `SettingsView.init`).

6. **`DocumentShareService` extraction** — **done (#107)**:
   `openRedactedDocument`, `shareDocument`, `confirmAndShareReviewCopy`,
   `shareFinalRedactedCopy`, `restoreEnvironmentValue`, `presentSharePicker`,
   and the `sharePresenter` seam (#98) moved into a `DocumentShareService`
   collaborator that takes the runner provider and
   `applyMetadataSettingsEnvironment` as constructor closures (the latter
   stays owned by the view model until #110's `ProcessRunner` extraction,
   since other call sites besides this flow use it too).
   `confirmAndShareReviewCopy`/`presentSharePicker` stay private to the
   collaborator; the view model keeps thin forwarding methods for
   `openRedactedDocument`/`shareDocument`/`shareFinalRedactedCopy` so
   `ContentView.swift` call sites are unchanged. `shareFinalRedactedCopy`
   now reports its error back to the caller by returning it (`String?`)
   instead of mutating `DocumentItem.errorMessage` itself; the view model's
   forwarder and the service's own `shareDocument` both apply the returned
   value the same way `shareFinalRedactedCopy` used to apply it directly, so
   external behavior (what ends up in `item.errorMessage`) is unchanged. The
   §3.2 item 6 environment save/restore characterization tests (from #101)
   pass unmodified, with only their setup helpers (`makeShareTestViewModel`,
   `runScenario`) updated to set `viewModel.documentShareService
   .sharePresenter` instead of the now-removed `viewModel.sharePresenter`.
   Verification per §3.3: `swift build` + `swift test` green, SwiftFormat
   lint clean, zero golden diffs.

7. **`OutputArtifactManager` extraction** — **done (#109)**: the largest
   mechanical slice (~500+ lines) -- `applyOutputArtifacts`,
   `findScrubReport`, output-directory resolution and permission handling
   (`outputSaveLocationPreference`, `resolveOutputDirectory`,
   `resolveTemporaryReportDirectory`, `requestMetadataOutputAccess`,
   `retryFileAccessPermissions*`), the metadata-report error helpers
   (`metadataReportErrorPayload`, `setMetadataReportError`,
   `setReportError`, `clearMetadataReportError*`, `clearReportError`),
   report viewing/saving (`openReport`/`openScrubReport`/
   `openMetadataReport`/`presentReport`/`resolvedHTMLURL`/
   `saveMetadataReport`/its `ToDownloads`/`ToDirectory` helpers/
   `exportMetadataReport`/`revealInFinder`), and preflight validation
   (`validateDestination`/`estimatedOutputBytes`/
   `generateScrubHTMLIfMissing`) all moved into an `OutputArtifactManager`
   collaborator taking `defaults`, the runner provider, an items-snapshot
   closure, and two error-sink closures (`setGlobalMetadataReportError`/
   `setGlobalReportError`) as constructor parameters, rather than reaching
   back into the view model. `metadataReportErrorMessage`/
   `metadataReportNeedsPermissionRetry`/`reportErrorMessage` stay
   `@Published` on the view model per this slice's own scope note, applied
   from those two closures; every item-scoped error field is set directly
   since `DocumentItem` is itself an `ObservableObject` reference passed
   in. The view model keeps thin forwarding methods for every call site --
   both `ContentView.swift`'s direct calls and its own remaining
   `processAllDocuments`/`scrubMetadataOnly`/`retryDocument`/
   `generateMetadataReportsInPlace`/`generateMetadataReport`/
   `scrubDocumentMetadataOnly` (staying on the view model until #110's
   `ProcessRunner` extraction and #111's `BatchCoordinator` extraction) --
   so none of those call sites changed;
   #101's `applyOutputArtifacts` filesystem characterization tests
   (§3.2 item 4) pass unmodified, construction-only unchanged.
   Verification per §3.3: `swift build` + `swift test` green, SwiftFormat
   lint clean, zero golden diffs.

8. **`ProcessRunner` extraction** — depends on slice 7 (uses
   `applyOutputArtifacts`) and slice 5 (uses `applyAdvancedSettingsEnvironment`
   /`applyMetadataSettingsEnvironment`, which should already be flowing
   through the unified migrator's settings resolution by this point).
   Requires the manual end-to-end smoke run (§3.3 item 5) since this is the
   direct PythonKit call boundary — the single highest-consequence piece
   in either file, since a regression here changes what actually gets
   redacted. Land last among the "service" extractions, with its own
   dedicated review pass.

9. **`BatchCoordinator` extraction** — depends on `ProcessRunner` (slice 8)
   and the `updateState()` characterization test (§3.2 item 1). Also the
   piece most tied to `processingTasks`/`Task` cancellation and pending-job
   persistence (`persistPendingBatchJobIfNeeded`, `resumePendingJob`,
   `discardPendingJob`), so pending-job recovery should get its own
   characterization test (simulate a crash mid-batch by constructing a
   `PendingBatchJobRecord` on disk and asserting `resumePendingJob`/
   `discardPendingJob` behavior) before this slice, not just before slice 9
   specifically — it protects slices 8 and 9 both. Land last of all nine
   slices; by this point `DocumentRedactionViewModel` should already be
   close to its target ~400–500 line size, so this final slice can be
   reviewed against a much smaller, easier-to-reason-about host file.

Each slice above is independently mergeable, does not require any other
slice to be in flight simultaneously (later slices depend on earlier ones
having *landed*, not being concurrent), and — except for slice 9 — touches
well under 10 files once call-site updates in `ContentView.swift` and any
other views bound to the affected `@Published`/public API are counted.
