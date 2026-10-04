# Spike results

One section per spike: question, method, result, decision. Proposed changes to ARCHITECTURE/PLAN are marked **Proposed (G0)**. The maintainer accepts or rejects them at gate G0.

Prototype code from S5 and S6 is in `spikes/`. It is reference code and the shell does not load it; the plugin entry points are still the A0 placeholders.

Environment for S5 and S6: HMSP-OMARCHYXPS, Omarchy 4.0.4, quickshell 0.3.1, mpv 0.41.0, mpv-mpris 1.2, a single 1920×1200 display at scale 1.5, bar on top, 2026-10-04. Driven over SSH from Hopebox. Input was injected with `wtype` (keys) and `ydotool` (pointer), and screenshots were taken with `grim`.

---

## S6 — Panel and bar-widget mechanics ✅

**Question.** How does a third-party bar widget open its own anchored panel? How is the panel sized and closed, how does it read theme tokens and register IPC, how do settings appear, and what does the capability facade block?

**Method.** Read `/usr/share/omarchy/shell/` (`README.md`, `shell.qml`, `services/PluginShellApi.qml`, `Ui/KeyboardPanel.qml`, `Ui/PopupCard.qml`, `Ui/Panel.qml`, `Ui/PluginBarApi.qml`), the stock audio panel, and `quickshell.spotify`. Built `spikes/s6-BarWidget.qml` and the S6 part of `spikes/s5-s6-Service.qml`, enabled the plugin live, and exercised it.

### Results

| Question | Answer | Verified how |
|---|---|---|
| Open an anchored panel from a 3p widget | The bar widget owns a `qs.Ui` **`KeyboardPanel`** with `anchorItem` set to its `BarIconButton`, `owner: root`, and `open` bound to a widget `opened` property. This is the same pattern as the stock audio panel and Spotify's mini player. The panel is a full-screen layer-shell surface (`omarchy-keyboard-panel`, overlay layer) with the card placed under the icon. | Screenshot: themed card centered under the book glyph, directly below the bar. `hyprctl layers` showed the surface while open and not after close. |
| Size | `contentWidth: fittedContentWidth(Style.space(380))` and `contentHeight: fittedContentHeight(content.implicitHeight, Style.space(560))`. Both clamp to the screen minus the bar and margins. | Rendered at about 570×137 logical px with the placeholder content. |
| Close on Esc | Wrap the content in `PanelKeyCatcher` and use `onCloseRequested: root.close()`. Set `focusTarget` on the KeyboardPanel to that catcher so it takes focus on map (it briefly primes Exclusive, then switches to OnDemand). | `wtype -k Escape` → `isOpen` false and the layer was gone. |
| Close on click-away | Built in. A full-screen `MouseArea` behind the card calls `owner.close()`. Clicks on the bar strip are forwarded to bar buttons. | `ydotool` click at (1200, 799) → closed. |
| One popout at a time | Built in. Opening calls `bar.requestPopout(owner)`, which closes the previous owner through `closeForPopoutSwitch()` (or `close()`). Implement `close()`, `closeForPopoutSwitch()`, and the `opened` and `popoutSwitchClosing` properties on the widget. | Ours open, then `omarchy-shell shell summon omarchy.audio` → ours closed. |
| Theme tokens | `import qs.Commons` gives `Color.popups.{background,text,border}`, `Color.{foreground,background,accent,muted,urgent}`, `Style.font.{body,heading,…,family}`, `Style.spacing.{sm,md,lg,popupPadding,…}`, `Style.space(px)`, and `Style.cornerRadius`. KeyboardPanel already draws a themed card and border. | Screenshot: themed background, accent border, heading, and muted text. **Not yet checked under three themes** (deferred to U1 and G4 so Chris's theme stayed as it was). |
| Shell IPC target | Put an `IpcHandler { target: "latentoperator.audible" }` in **Service.qml** and call it with `omarchy-shell latentoperator.audible <method> [args…]`. Arguments and return values are strings. A Hyprland bind runs `omarchy-shell latentoperator.audible toggle`. | `ping`, `toggle`, `isOpen`, and `surfaceCount` worked. `qs ipc show` listed the target. |
| Why the service, not the widget | A bar widget is instantiated once **per monitor**. A second `IpcHandler` with the same target logs "Handler was registered but will not be used because another handler is registered" and is ignored. The service is a single instance. | The same warning appears in the journal for other plugins that register in widgets. |
| Widget ↔ service | The widget's `bar.shell.serviceFor("latentoperator.audible")` returns our service. A facade only resolves the plugin's own id. The widget registers itself with the service so IPC can drive the drawer (Spotify does the same with `registerPlayerSurface`). | `surfaceCount` = 1 with one monitor. |
| Settings schema | `barWidget.defaults` and `barWidget.schema` from the manifest are passed to the widget registry and the settings form (`shell.qml` around line 1408). Values arrive in the **widget** as `settings` (the inline `shell.json` entry), read with `setting(name, fallback)`. The service has no direct settings access, so the widget must push them, like Spotify's `spotify.applySettings(settings)`. | Read from source. The form was not opened. |
| Capability facade | Third-party plugins get `PluginShellApi` (`serviceFor` and `summon`/`hide`/`toggle`/`isPluginOpen` for their own id, plus `updateEntryInline`) and the `PluginBarApi` bar facade (`requestPopout`/`releasePopout`, `clickTargets`, tooltips, `run(cmd)`, scalar bar state). There are no first-party services and no auth services. `Quickshell.execDetached`, `Process`, `Socket`, and `FileView` are **not** blocked. | Read from source. `execDetached` and `Socket` were used in S5. |

### Findings that change the plan

1. **Proposed (G0): drop the `panel` kind and `Panel.qml`, and host every view in the bar widget's KeyboardPanel.** When a manifest declares `panel`, `omarchy-shell shell summon/toggle <id>` loads the plugin's `Panel.qml` through the panel Loader as a separate, non-anchored surface instead of opening the bar drawer (`shell.qml` `isBarWidgetPanelPlugin`). That is two UIs to keep in sync. Library, Mini, and Full in one KeyboardPanel that grows for Full matches the decision for "panel-style maximize, not a separate window". Our own IPC target covers hotkeys. Manifest kinds become `service` and `bar-widget`.
2. **Proposed (G0): name the IPC target `latentoperator.audible`, not `omarchy-audible`.** That matches the plugin id and avoids collisions. Update ARCHITECTURE §6 and P5.
3. **All UI and player state must live in the service.** There is one drawer per monitor because each monitor's widget owns one, so the widget instances are views only. ARCHITECTURE already says this; U1 should state it explicitly.
4. **Dev reload: a `Service.qml` change needs `omarchy-restart-shell`.** The launcher sets `QS_DISABLE_FILE_WATCHER=1`. Neither `git pull` into the symlinked dev dir nor `omarchy-shell shell rescanPlugins` loaded the new service; `qs ipc show` kept the old method list until the shell restarted. Widget changes reloaded on rescan. Fix the "saving a file reloads it" lines in AGENTS.md and WORKFLOW.md.
5. Noise, not ours: `Bar.qml[2004]: Cannot assign to read-only property "moduleName"` appears on every plugin rescan. It occurred 96 times in the 7 days before this spike.

---

## S5 — mpv under Quickshell ✅

**Question.** Can the service start mpv detached, control and observe it over JSON IPC through `Quickshell.Io.Socket`, and reattach after a shell restart? Should we use `execDetached` or `systemd-run --user --scope`?

**Method.** Added an mpv controller to `spikes/s5-s6-Service.qml`, exposed through IPC methods (`mpvStart <scope|plain>`, `load <path> <startSec>`, `pause yes|no`, `seek <s> <mode>`, `chapter <i>`, `quit`, `status`). Generated a 180 s, 3-chapter sine m4b with ffmpeg (`lavfi` sine plus an FFMETADATA chapter file) at low volume. Restarted the shell with `omarchy-restart-shell` during playback in both launch modes.

### Results

| Check | Result |
|---|---|
| Start detached | `Quickshell.execDetached(["systemd-run","--user","--scope","--quiet","--collect","--unit=omarchy-audible-mpv-<ts>", "mpv", …, "--input-ipc-server=$XDG_RUNTIME_DIR/omarchy-audible/mpv.sock"])` ✅ mpv runs in its own `app.slice/omarchy-audible-mpv-*.scope`. |
| Connect and observe | `Socket` plus `SplitParser` (newline) ✅. `observe_property` delivered `time-pos`, `pause`, `chapter`, `chapter-list` (3), `path`, and `duration` (180). |
| Resume with `loadfile <path> replace 0 start=<s>` | ✅ `start=42` → `time-pos` 43.5 after 1.5 s. |
| `set_property pause`, `seek <s> absolute`, `set_property chapter <i>` | ✅ All three applied and were reflected in the observed properties. |
| **Survives `omarchy-restart-shell` and reattaches** | ✅ Tested in both modes. Same mpv PID before and after. The new service instance reconnected on its first retry and had live state within 3 s (`timePos` 155.9, `chapter` 2, `pause` false), and the position kept advancing. |
| Crash detection | ✅ After `kill -9` on mpv, `connected` went false within 1.5 s. |
| Audio path | A scope-launched mpv using the session environment reports `current-ao = pipewire`. The shell-launched instance played (its position advanced), but its AO was not queried separately. |

### Decision: `systemd-run --user --scope`

Both modes survive a shell restart. Plain `execDetached` reparents mpv to the user manager but leaves it **inside the compositor's cgroup** (`session.slice/wayland-wm@hyprland.desktop.service`). Anything that stops or restarts that unit kills playback, and the process can't be found by name. A user scope gives mpv its own cgroup, a unit name that systemd can find, stop, and account for, and the same session environment. If `systemd-run` is missing, fall back to plain `execDetached`.

Optional (P2): use a **fixed** unit name (`omarchy-audible-mpv`) so systemd refuses a second mpv. That gives a single-instance guard for free.

### Pitfalls P2 must handle

1. **Subscribe on the derived `connected` property, not in `Socket.onConnectionStateChanged`.** With `connected: true` set at creation, the socket can connect before `Loader.item` is assigned, so `send()` sees no item and the subscriptions are silently dropped. The first build hit exactly this: connected with no events. Fixed by `onMpvConnectedChanged: if (mpvConnected) subscribe()`.
2. **A failed connect leaves a dead socket object.** Recreate the `Socket` on each retry by toggling a `Loader`. Spotify's `BackendClient.qml` does the same.
3. **The socket file outlives mpv.** After `quit`, `mpv.sock` was still there. "Socket exists" does not mean "mpv is alive"; only a successful connect does. mpv replaces the path when it starts.
4. **`execDetached` returns nothing**, so a failed launch can only be detected as "no connection within N seconds". Do not use `Process` to launch mpv: a `Process` child belongs to the shell and dies with it.
5. **Idle cost (R4):** the spike retried the connection every second forever whenever mpv was absent. P2 should retry only while a book is supposed to be loaded (according to `state.json`), use backoff, and give up after a bounded number of attempts at startup.

---

## S1–S4

Not started. They need the real Audible account on the laptop.
