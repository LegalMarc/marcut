import Foundation
import IOKit.pwr_mgt

/// Thin wrapper around IOKit's power-assertion API (`IOPMAssertionCreateWithName` /
/// `IOPMAssertionRelease`). Kept separate from `PowerAssertionGuard` so the guard's
/// reference-counting logic can be unit-tested with injected fakes instead of touching real
/// system power-management state.
///
/// `PreventUserIdleSystemSleep` only prevents *idle* sleep (the Mac dimming/sleeping on its own
/// after inactivity) -- it does not prevent a forced lid-close or Apple-menu "Sleep" while the
/// app holds it. That's expected and is why B5 pairs this with wake-time health-checking
/// (`DocumentRedactionViewModel.handleSystemWake()`) rather than relying on the assertion alone.
///
/// Sandbox note: this is plain userspace IOKit power-management API, not a hardware/IOKit
/// user-client that requires a sandbox entitlement -- confirmed no new entry is needed in
/// `build-scripts/Marcut.entitlements` for this call to succeed under App Sandbox.
enum SystemPowerAssertion {
    /// Acquires a `PreventUserIdleSystemSleep` assertion with the given human-readable reason
    /// (visible in `pmset -g assertions` / Activity Monitor's power tab). Returns `nil` if the OS
    /// refused to grant one -- callers must treat that as "fail open": a missed assertion just
    /// means the Mac could idle-sleep mid-run, not a redaction-correctness issue, so it must never
    /// crash or block processing.
    static func acquire(reason: String) -> IOPMAssertionID? {
        var assertionID: IOPMAssertionID = 0
        let result = IOPMAssertionCreateWithName(
            kIOPMAssertionTypePreventUserIdleSystemSleep as CFString,
            IOPMAssertionLevel(kIOPMAssertionLevelOn),
            reason as CFString,
            &assertionID
        )
        return result == kIOReturnSuccess ? assertionID : nil
    }

    /// Releases a previously acquired assertion. Best-effort: `IOPMAssertionRelease` returning a
    /// non-success code here isn't actionable (the assertion is either already gone or the OS is
    /// tearing down), so it's logged rather than surfaced.
    static func release(_ assertionID: IOPMAssertionID) {
        let result = IOPMAssertionRelease(assertionID)
        if result != kIOReturnSuccess {
            DebugLogger.shared.log(
                "⚠️ IOPMAssertionRelease returned \(result) for assertion \(assertionID)",
                component: "PowerAssertion"
            )
        }
    }
}

/// RAII-style, reference-counted holder for the "keep this Mac awake" assertion held while
/// documents are processing or a model is downloading (B5).
///
/// Multiple overlapping callers (e.g. a model download kicked off mid-batch) share one
/// underlying OS assertion: the Nth `begin()` while one is already held is a no-op at the OS
/// level, and the assertion is only released once every `begin()` has a matching `end()` -- an
/// unmatched extra `end()` is clamped at zero rather than allowed to underflow into releasing a
/// still-needed assertion (or crash). This is what makes it safe to call `begin()`/`end()` from
/// multiple independent call sites (batch processing, model download) without coordinating
/// between them, and to call it repeatedly from an edge-triggered call site (see
/// `DocumentRedactionViewModel.updateState()`) without leaking on every redundant call.
///
/// Acquire/release are injectable so tests can exercise the counting/lifecycle logic without
/// touching real system power-management state (see `MarcutAppTests.swift`). Not `Sendable` and
/// not safe to share across actors other than by routing every call through the same actor --
/// every real call site in this app is `@MainActor`, hence this type is too.
@MainActor
final class PowerAssertionGuard {
    static let shared = PowerAssertionGuard()

    private let reason: String
    private let acquireAssertion: (String) -> IOPMAssertionID?
    private let releaseAssertion: (IOPMAssertionID) -> Void

    private var assertionID: IOPMAssertionID?
    private(set) var activeCount: Int = 0

    init(
        reason: String = "Marcut is processing documents",
        acquire: @escaping (String) -> IOPMAssertionID? = SystemPowerAssertion.acquire,
        release: @escaping (IOPMAssertionID) -> Void = SystemPowerAssertion.release
    ) {
        self.reason = reason
        self.acquireAssertion = acquire
        self.releaseAssertion = release
    }

    deinit {
        // Defensive only: `shared` lives for the process lifetime and never deinitializes.
        // Test-local instances that still hold an assertion when torn down (e.g. a test that
        // asserts the *count* without calling a final `end()`) must not leak past their own
        // lifetime.
        if let assertionID {
            releaseAssertion(assertionID)
        }
    }

    /// Marks one more reason the Mac should stay awake. Idempotent at the OS level -- only the
    /// first concurrent caller actually creates the assertion; a failed acquire (OS refused, or a
    /// prior release already happened) is retried on the next `begin()` that brings the count off
    /// zero.
    func begin() {
        activeCount += 1
        guard assertionID == nil else { return }
        assertionID = acquireAssertion(reason)
    }

    /// Retires one reason the Mac should stay awake. Only releases the underlying assertion once
    /// every `begin()` has been matched.
    func end() {
        guard activeCount > 0 else { return }
        activeCount -= 1
        guard activeCount == 0, let assertionID else { return }
        releaseAssertion(assertionID)
        self.assertionID = nil
    }

    /// Whether an OS-level assertion is currently held. `false` if the count is zero, or if the
    /// count is positive but the OS refused every `acquire()` attempt so far.
    var isHoldingAssertion: Bool {
        assertionID != nil
    }
}
