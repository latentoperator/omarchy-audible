import QtQuick
import Quickshell
import Quickshell.Io

import "lib/Ipc.js" as Ipc
import "lib/LibraryUi.js" as LibraryUi
import "lib/Panel.js" as Panel
import "lib/Signin.js" as Signin

// The shell IPC target (ARCHITECTURE 6), split out of Service (P9). It must
// stay the one IpcHandler for `latentoperator.audible` and a child of the
// service: a widget is created once per monitor (SPIKE-RESULTS "Why the
// service, not the widget"). Every argument and return value is a string:
// "ok", or a short error string. Nothing here throws. Each method calls the
// service or one of its children; nothing here keeps state.
Item {
  visible: false
  width: 0
  height: 0

  // The Service, and the children of it the methods reach.
  property var service: null
  property var library: null
  property var player: null
  property var runner: null
  property var store: null
  property var sync: null
  property var signin: null

  IpcHandler {
    target: "latentoperator.audible"

    function toggle(): string {
      var surface = service.primarySurface()
      if (!surface) return "error: no surface"
      surface.toggle()
      return "ok"
    }

    function openLibrary(): string {
      var surface = service.primarySurface()
      if (!surface) return "error: no surface"
      surface.open()
      service.showView(Panel.VIEW_LIBRARY)
      return "ok"
    }

    function playPause(): string {
      return service.playPause()
    }

    function skip(seconds: string): string {
      var value = Ipc.parseSeconds(seconds)
      if (value === null) return "error: bad seconds"
      if (!player.loaded) return "error: nothing loaded"
      player.skip(value)
      return "ok"
    }

    function nextChapter(): string {
      if (!player.loaded) return "error: nothing loaded"
      player.nextChapter()
      return "ok"
    }

    function prevChapter(): string {
      if (!player.loaded) return "error: nothing loaded"
      player.prevChapter()
      return "ok"
    }

    // Test methods so agents can drive the service without input. Each one
    // works only in fake mode and returns Ipc.DEV_ONLY otherwise (H1 F27);
    // Ipc.js lists the public and read-only status methods that stay.
    function play(asin: string): string { if (!service.fake) return Ipc.DEV_ONLY; service.noteIntent(asin); return service.playBook(asin, -1) }
    function playAt(asin: string, startSec: string): string { if (!service.fake) return Ipc.DEV_ONLY; service.noteIntent(asin); return service.playBook(asin, Number(startSec) || 0) }
    function pause(): string { if (!service.fake) return Ipc.DEV_ONLY; player.pause(); return "ok" }
    function resume(): string { if (!service.fake) return Ipc.DEV_ONLY; player.resume(); return "ok" }
    function chapter(index: string): string { if (!service.fake) return Ipc.DEV_ONLY; player.setChapter(Number(index) || 0); return "ok" }
    function speed(value: string): string { if (!service.fake) return Ipc.DEV_ONLY; player.setSpeed(Number(value)); return "ok" }
    function volume(value: string): string { if (!service.fake) return Ipc.DEV_ONLY; player.setVolume(Number(value)); return "ok" }
    function sleepMinutes(minutes: string): string { if (!service.fake) return Ipc.DEV_ONLY; player.setSleepTimer(Number(minutes) || 0); return "ok" }
    function sleepChapter(): string { if (!service.fake) return Ipc.DEV_ONLY; player.setSleepEndOfChapter(); return "ok" }
    function sleepCancel(): string { if (!service.fake) return Ipc.DEV_ONLY; player.cancelSleep(); return "ok" }
    function quitPlayer(): string { if (!service.fake) return Ipc.DEV_ONLY; service.quitPlayer(); return "ok" }
    function playerStatus(): string { return service.playerSummary() }
    function libraryQuery(sort: string, filter: string, search: string): string { if (!service.fake) return Ipc.DEV_ONLY; return service.libraryQuery(sort, filter, search) }
    function flushState(): string { if (!service.fake) return Ipc.DEV_ONLY; store.flush(); return "ok" }
    function syncNow(): string { if (!service.fake) return Ipc.DEV_ONLY; return service.run("sync", [], "ipc") ? "ok" : "refused" }
    function pick(asin: string): string { if (!service.fake) return Ipc.DEV_ONLY; return service.pick(asin) }
    function answer(choice: string): string { if (!service.fake) return Ipc.DEV_ONLY; return service.answerAsk(choice === "resume") }
    function confirmDownload(): string { if (!service.fake) return Ipc.DEV_ONLY; return service.confirmDownload() }
    function cancelConfirm(): string { if (!service.fake) return Ipc.DEV_ONLY; return service.cancelConfirm() }
    function removeBook(asin: string): string { if (!service.fake) return Ipc.DEV_ONLY; return service.removeBook(asin) }
    function libraryState(): string {
      return JSON.stringify({ "list": service.listState, "ask": service.askAsin, "confirm": service.confirmAsin, "reopen": service.reopenAsin,
        "syncing": service.syncing, "lastSyncCode": service.lastSyncCode, "count": library.count,
        "total": library.allRows.length, "storage": LibraryUi.storage(library.localBooks) })
    }
    function onboardingState(): string {
      var st = service.status || {}
      return JSON.stringify({ "step": service.onboardingStep, "phase": service.loginPhase,
        "reconnecting": service.reconnecting, "authFailed": service.authFailed, "error": service.onboardingError,
        "pasteRejected": service.pasteRejected, "pasteEmpty": service.pasteEmpty, "notice": service.clipboardNotice.length > 0,
        "authenticated": st.authenticated === true, "venvReady": st.venv_ready, "missing": st.missing || [],
        "account": st.account || null, "marketplace": st.marketplace || null, "view": service.view,
        "heldInputs": Object.keys(runner.inputs).length })
    }
    // Onboarding actions for tests: fake mode only, so IPC can never sign in,
    // sign out or set up the real account.
    function fakeOnboarding(action: string, arg: string): string {
      if (!service.fake) return Ipc.DEV_ONLY
      if (action === "status") { service.checkStatus(); return "ok" }
      if (action === "setup") return service.startSetup()
      if (action === "login") return service.startLogin(arg.length > 0 ? arg : Signin.DEFAULT_MARKETPLACE)
      if (action === "finish") return service.finishLogin(arg)
      if (action === "import") return service.importCliLogin()
      if (action === "logout") return service.disconnect()
      if (action === "reconnect") { service.reconnect(); return "ok" }
      if (action === "authfail") { signin.noteAuthFailed(); return "ok" }
      return "error: unknown action"
    }
    // Fake mode only: a download that fails with a `--fake-fail` mode.
    function fakeFailGet(asin: string, mode: string): string {
      if (!service.fake) return Ipc.DEV_ONLY
      return service.run("get", [asin, "--fake-fail", mode], "download") ? "ok" : "refused"
    }
    function autoRemove(value: string): string { if (!service.fake) return Ipc.DEV_ONLY; service.autoRemoveFinished = value === "on"; return "ok" }
    function pushState(): string { return JSON.stringify({ "queue": sync.queue, "flushing": sync.flushing, "last": sync.lastResult,
      "staleCount": sync.consecutiveStale, "staleNotice": sync.staleNotice,
      "failedFlushes": sync.failedFlushes, "retryMs": sync.retryIntervalMs }) }
    // Opens the panel on a view (Onboarding.view still decides: Mini or Full
    // with nothing loaded shows the Library). Returns the view shown. Fake
    // mode only: opening the panel can read positions or start a sync.
    function view(name: string): string {
      if (!service.fake) return Ipc.DEV_ONLY
      if (Panel.VIEWS.indexOf(name) === -1) return "error: unknown view"
      var surface = service.primarySurface()
      if (!surface) return "error: no surface"
      if (!surface.opened) surface.open()
      service.showView(name)
      return service.view
    }
    function chapterList(state: string): string {
      if (!service.fake) return Ipc.DEV_ONLY
      if (state !== "open" && state !== "close") return "error: open or close"
      if (state === "open" && (!player.loaded || player.chapters.length === 0)) return "error: no chapters"
      service.chapterListOpen = state === "open"
      return "ok"
    }
    function panelState(): string {
      var open = service.surfaces.some(function(s) { return s.opened === true })
      return JSON.stringify({ "open": open, "view": service.view, "chapterList": service.chapterListOpen,
        "glyph": service.barGlyph, "tooltip": service.tooltipText })
    }
    function events(): string {
      return service.recentEvents.map(function(e) { return e.label + "  " + e.text }).join("\n")
    }
  }
}
