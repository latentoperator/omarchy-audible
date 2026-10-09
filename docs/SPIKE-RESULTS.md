# Spike results

One section per spike: question, method, result, decision. Proposed changes to ARCHITECTURE/PLAN are marked **Proposed (G0)**. The maintainer accepts or rejects them at gate G0.

Prototype code from S5 and S6 is in `spikes/`. It is reference code and the shell does not load it; the plugin entry points are still the A0 placeholders.

Environment for S5 and S6: HMSP-OMARCHYXPS, Omarchy 4.0.4, quickshell 0.3.1, mpv 0.41.0, mpv-mpris 1.2, a single 1920×1200 display at scale 1.5, bar on top, 2026-10-04. Driven over SSH from Hopebox. Input was injected with `wtype` (keys) and `ydotool` (pointer), and screenshots were taken with `grim`.

---

## R4 — Idle cost — measured; no offenders, no code change

**Question.** SCOPE §8.7: with nothing playing, does the plugin run timers, poll or start processes, and is its resident memory (excluding mpv) under ~100 MB?

**Method.** HMSP-OMARCHYBEE, Omarchy 4.0.4, Quickshell 0.3.1, live folder on `main`'s code commit `cc0cfa2`, 2026-10-09, read-only (no account calls). Real mode had Chris's book loaded and **paused** (the usual idle state: mpv alive, nothing playing); fake mode had nothing loaded. Two scripts, kept in `spikes/`:
1. *Code audit:* every `Timer`, `FileView`, `Socket`, `Process` and animation in `Service.qml`, `BarWidget.qml` and `qml/`.
2. *`spikes/r4_idle.py`* (root, read-only `/proc`): over a window, the shell's CPU ticks and RSS, the paused mpv's CPU ticks and context switches, every process whose parent chain reaches the shell (polled every 50 ms), and every file whose mtime changed under the plugin's real and fake config/data/runtime dirs.
3. *`spikes/r4_mem.sh`*: a fresh shell's RSS/PSS 75 s after `omarchy-restart-shell`, with our bar entry and with it removed from `shell.json` (backed up and restored, `cmp` clean), then with the panel opened and closed; three rounds.

**Result — timers and polling.** Every repeating timer is gated on playback or a pending job: Service's 10 s save and 60 s push (`running: player.playing`), the controller's 250 ms sleep tick (`sleepTimer !== null && playing`), Full view's 1 s clock (`visible && sleepTimer !== null`), and `PositionSync`'s retry (`queue.length > 0 && !flushing`, 1 min doubling to 30 min, only while a position push is unsent; F18). All other timers are single-shot. No `FileView` sets `watchChanges`, there is no infinite animation, and the mpv `Socket` is event-driven: a paused mpv sends nothing (0 context switches and 0 CPU ticks in every window below). The only work on a panel open is one-shot and on demand: a `sync` when the catalog is older than `syncOnOpenHours`, and the catch-up read.

| Window | Shell children from our plugin | Files changed in our dirs | Paused mpv |
|---|---|---|---|
| Real, panel closed, 180 s | 0 | 0 | 0 ticks, 0 switches |
| Real, Library open, 120 s | 0 | 0 | 0 ticks, 0 switches |
| Fake, nothing loaded, panel closed, 180 s | 0 | 0 | — |

The whole shell used 159–171 ticks per window (about 1 % of one core). That is other plugins: in the 180 s real window the shell started 676 processes, none ours, 391 of them from `io.github.fabean.herdr`'s `state.sh` and 240 its `ssh` agent polls.

**Result — memory.** The shell is one process, so the plugin's share is the difference between fresh shells with and without it.

| Round | RSS with / without | PSS with / without | Plugin share (RSS / PSS) | Panel open (RSS) | Panel closed again |
|---|---|---|---|---|---|
| 1 | 697.5 / 655.9 MB | 598.5 / 557.6 MB | 41.7 / 41.0 MB | +13.3 MB | −0.4 MB |
| 2 | 669.0 / 625.7 MB | 570.6 / 527.1 MB | 43.3 / 43.5 MB | +28.6 MB | +14.8 MB |
| 3 | 669.8 / — | 571.1 / — | — | +56.3 MB | +31.6 MB |

So the plugin costs about **42 MB** at rest with a book loaded, under the ~100 MB target; an open Library (91 rows, covers decoded at row size) adds 13–56 MB while it is open, part of which Qt keeps cached after it closes. Fresh shells vary by ±30 MB from run to run, so these figures are good to about that. Round 3's "without" shell crashed on start (SIGSEGV in `QQmlObjectCreator::finalize` → `__dynamic_cast`, Quickshell 0.3.1, with our entry already removed from `shell.json`), so that round has no valid "without" reading. The paused mpv held 42–49 MB and is outside the target.

**Decision.** No offenders; no code change. R2–R7 keep the rule: no new repeating timer or polling that runs while nothing plays.

---

## U9 — Pause lag (G4 finding) — measured; nothing in our launch options to change

**Question.** Chris hears about a second of audio after ⏯. Is any of it in the plugin or in how we start mpv?

**Method.** HMSP-OMARCHYBEE, mpv 0.41.0 on PipeWire 1.6.8 (`ao=pipewire`, quantum 1024 at 48 kHz), 2026-10-07, in fake mode, with `launchMpv` as of P8 (`--volume`, `--speed`). Two parts, each five times (scripts in `spikes/u9_*.py`):
1. *The plugin's path end to end:* with the fake book playing, time the public `omarchy-shell latentoperator.audible playPause` call, mpv's `pause` property-change event (read by a second client on the fake mpv's socket), and the last 10 ms block with any signal on the default sink's monitor (`parec`, blocks stamped on arrival; the monitor reads exactly 0 when paused).
2. *mpv and PipeWire alone:* a standalone mpv with the plugin's exact launch arguments playing a 440 Hz sine into a temporary null sink (`pactl load-module module-null-sink`, removed afterwards; the default sink was never changed), from the `set pause yes` send to the last block with signal. Repeated with `--audio-buffer=0.05` (default 0.2 s), `--pipewire-buffer=20` (default `native`) and `--speed=3`. Then three minutes of play each at 1× and 3× into the null sink, checking mpv's log for underruns.

**Result.**

| Gap | Median | Range |
|---|---|---|
| `playPause` call → mpv reports `pause` (includes the `omarchy-shell` CLI's own start-up) | 32 ms | 31–39 ms |
| mpv reports `pause` → last sample at the sink | 10 ms | 3–13 ms |
| `playPause` call → last sample at the sink, end to end | 41 ms | 34–49 ms |
| `set pause yes` → silence, standalone, default arguments | 11 ms | 6–12 ms |
| same, `--audio-buffer=0.05` | 9 ms | 7–15 ms |
| same, `--pipewire-buffer=20` | 9 ms | 8–14 ms |
| same, `--speed=3` | 9 ms | 9–15 ms |

mpv does not play out its audio buffer on pause, so neither option changes anything. No underrun was logged in any run or in the three-minute plays at 1× and 3×. From ⏯ to silence on the sink's monitor (PipeWire's mix, before the ALSA device buffer) is about 40 ms. `PULSE_LATENCY_MSEC` does not apply: mpv uses its native PipeWire output, not Pulse.

**What's left is not measured here.** It would be after PipeWire's mix: the ALSA device buffer of the line-out sink (Realtek ALC897 on `snd_hda_intel`, `alsa_output.pci-0000_04_00.6.HiFi__Line2__sink`) and whatever is attached to it. A monitor recording can't see that buffer, and measuring it needs a loopback cable or ears. A plain PipeWire ALSA sink buffers tens of milliseconds, not a second, so the likely place for most of the second is the speakers themselves, for example powered speakers with their own processing. That is an inference, not a measurement, until Chris's listening check below.

Also seen: while a Moonlight session is connected, Sunshine makes `sink-sunshine-stereo` the default (muted locally) and both mpv streams follow it. Audio heard through Moonlight then also carries Sunshine's encode and the network, which no player option can remove.

**Decision.** No change to `launchMpv`. The check for Chris (FOLLOWUPS-desktop §5, item 7): at BEE, with no Moonlight session, play any file in plain `mpv` and press Space. If the same second is there, it's the speakers or the sound card, not the plugin.

---

## S7 — Play locked files, keep no decrypted copy ✅ (go)

**Question.** Can mpv play the aaxc/aax file exactly as Audible sent it, unlocking it only in memory, so no DRM-free `.m4b` ever lands on disk, without the key ever appearing in a process's argv?

**Method.** Run on HMSP-OMARCHYBEE on 2026-10-06 in real mode, without touching the shell or the running service. A throwaway script downloaded the shortest non-local book (145 min) twice into a `0700` cache directory, once `--aaxc` and once `--aax`, using the plugin's own login and audible-cli. A separate headless mpv 0.41.0 (`--no-config --ao=null`, its own `0600` socket) was used, not the plugin's player. **Only counts, timings and booleans left the machine.** No titles, ASINs, keys or audio were copied off it, and everything was deleted afterward.

Two ways of passing the key were tried, and both work with the key never in argv:
- **Per file over the IPC socket:** `loadfile <path> replace -1 {"demuxer-lavf-o": "audible_key=…,audible_iv=…", "chapters-file": "<ffmetadata>", "start": "<s>"}` (aax: `activation_bytes=…`). This fits `PlayerController` as it is: one long-lived mpv, a new key with each book.
- **An owner-only `--include` file** containing `demuxer-lavf-o=…`, for one-shot runs.

### Results

| | aaxc (voucher key/iv) | aax (activation bytes) |
|---|---|---|
| Size on disk | 140 MB (unchanged; no second copy) | 140 MB |
| Load → first audio | 35 ms | 48 ms |
| Seek to 5 / 20 / 50 / 95 % | ≤ 1 ms each | ≤ 1 ms each |
| Skip ±15 s, +30 s | ≤ 1 ms each | ≤ 1 ms each |
| CPU at 1× / 3× speed | 0.8 % / 3.0 % | 0.6 % / 2.8 % |
| Resume at a saved position (37 %) | exact (0.00 s off), 41 ms | exact, 47 ms |
| Chapters via `chapters-file` built from `chapters.json` | 2 of 2, starts exact (0 ms) | 2 of 2, exact |
| Key in any process's argv (`/proc/*/cmdline`), before and while playing | none | none |

**The audio is really unlocked, not noise.** 20-second slices at 1 min and 67 min were decoded to PCM: aaxc and aax give **bit-identical** PCM with non-silent levels and zero decoder errors. Controls: aaxc with no key produced thousands of decoder errors and almost no audio; aax with wrong activation bytes is refused at open (`[aax] mismatch in checksums`). (A first pass that only checked `file-loaded` and `duration` wrongly suggested that no key was needed. The header opens without a key, but the audio doesn't decode. Use the PCM check, not `file-loaded`, in B11's tests.)

**Not covered here:**
- **Position push / `acr`:** not exercised, because the code doesn't change. `acr` comes from content metadata (cached in `meta.json`), not from the audio file.
- **A book with 100+ chapters:** the test book had 2. `chapters-file` is ordinary ffmetadata, the same file `get` already builds, so no difference is expected. Check one long book during B11's acceptance.
- **The real `PlayerController` in the shell:** this is B11's job.
- **mpv logging:** the key travels as a loadfile option. The plugin's mpv has no log file today; B11 must keep it that way, or make sure no log level writes option values.

**The key is readable over IPC** (`get_property demuxer-lavf-o`) by anyone who can open the socket. The socket is `0600` in the user's runtime dir, so that is the same user who can already read `~/.config/omarchy-audible/`. This is acceptable, and B11 should clear the option after load anyway.

### Decision D7: go (Chris, 2026-10-06)

Stop storing decrypted copies. B11: `get` keeps the locked file and writes the key material `0600` beside it (aaxc: key/iv from the voucher; aax: a reference to the account's activation bytes, not a copy). `get` writes the ffmetadata chapter file and drops the ffmpeg conversion, so the free-space check falls from ~2.1× to ~1.1×. `PlayerController` passes the key and chapter file as `loadfile` options over the socket, never argv. `remove` deletes the key file too. Existing `.m4b` books keep playing as they are, and only new downloads are locked (BEE has one local book).

Chris accepted the listing risk knowingly. The marketplace has no written DRM rule (checked 2026-10-06: `SUBMISSION.md`, `SECURITY.md`, `NOTICE.md` and the issue templates), no listed plugin unlocks DRM, and a maintainer can still decline the plugin or act on a rights-holder's removal request.

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

## S2, S3, S4: shared method

Run on HMSP-OMARCHYXPS on 2026-10-04, using the existing `~/.audible` login, audible 0.12.0 / audible-cli in its uv tool venv (Python 3.14.7), and ffmpeg. Scripts are in `spikes/`. They ran from a private `0700` directory, and the downloads went to a `0700` cache directory and `$XDG_RUNTIME_DIR`. **Only counts, field names and timings left the laptop.** No titles, ASINs, keys or audio were copied off it. Everything was deleted afterward.

---

## S4 — Catalog fields and multi-part books ✅

**Question.** What response groups give the UI fields without timeouts, and how do multi-part books behave?

### Results

| Check | Result |
|---|---|
| Groups from ARCHITECTURE §4.5 (`product_desc,media,contributors,series,product_attrs,listening_status,percent_complete,is_finished`), `num_results=50`, paged | ✅ 91 items, 2 pages, **0.9 s**. No timeout. Adding `relationships` took 2.1 s. |
| Fields present (of 91) | `title` 91, `subtitle` 43, `series` 57 (`[{asin, title, sequence, url}]`, where `sequence` is a string), `authors`/`narrators` 91 (`[{asin, name}]`), `runtime_length_min` 91, `content_type` 91, `content_delivery_type` 91, `percent_complete` 91, `is_finished` 91, `listening_status` 91 (`{is_finished, percent_complete, time_remaining_seconds, finished_at_timestamp}`), `purchase_date`, `release_date`, `library_status.date_added`, `language`, `is_listenable`. |
| Covers | With these groups, `product_images` has only a `"500"` key (a 500 px URL). Asking for other sizes through the `image_sizes` parameter was **not tested**. B4 should either downscale the 500 px image or test `image_sizes=252`. |
| `content_type` | `Product` 89, `Lecture` 2. This library has no podcasts. **Lectures must not be filtered out.** B4 should drop only podcast types (`Podcast*`), which need a library that has them to confirm. |
| `content_delivery_type` | `MultiPartBook` 60, `SinglePartBook` 31. |
| Multi-part shape | Each `MultiPartBook` lists its parts as `relationships` of type `component/child` (137 parts across the 60 books). **None of the parts are separate library items.** Two library items are themselves parts whose parent is not owned, and they behave like normal books. |
| Multi-part content | Content metadata succeeded for all 60. Each is **one** content item: API runtime / catalog runtime = 1.000–1.001, 2–66 top-level chapters, codec `mp4a.40.2` (43 at 44 kHz, 17 at 22 kHz). |
| Multi-part download (S2) | One `.aax` file, duration exact (see S2). |
| Position lookup batch limit | **25 ASINs per `lastpositions` call.** 40 failed with "No more than 25 asins allowed". The plan said ≤ 50. |

### Decision D5 (proposed for G0): multi-part books need no special handling

`MultiPartBook` is how Audible's catalog describes the book. Download, decrypt, chapters and runtime all behave like a single book. Drop the `multipart` flag from `catalog.json`, or keep it for information only.

Fixture: `fixtures/library-sample.json` has 5 items with the **real field shapes and invented values**: a single-part book, a series entry, a multi-part book, a lecture, and a finished book.

---

## S2 — Download and decrypt both formats ✅

**Question.** Using a plugin-owned config dir, can we download and decrypt both `.aax` and `.aaxc` to m4b with chapters intact?

**Method.** Created a private `AUDIBLE_CONFIG_DIR` containing a copy of the auth file and a minimal `config.toml` (`primary_profile = "plugin"`). Downloaded the shortest multi-part book with `--aax` and the shortest single-part book with `--aaxc`, both with `--chapter -q best -f asin_only`, then decrypted each with `ffmpeg -c copy`.

**No aaxc-only book exists in this library.** Every item lists `aax` among its codecs. To prove the aaxc path anyway, it was **forced** with `--aaxc`.

### Results

| | `.aax` (multi-part, 544 min) | `.aaxc` (single-part, 145 min) |
|---|---|---|
| Download | 264 MB in 49 s | 140 MB in 26 s |
| Files | `<ASIN>-LC_64_22050_stereo.aax`, `<ASIN>-chapters.json` | `<ASIN>-AAX_44_128.aaxc`, `.voucher`, `-chapters.json` |
| Decrypt command | `ffmpeg -activation_bytes <hex> -i in.aax -map 0:a -c copy out.m4b` | `ffmpeg -audible_key <key> -audible_iv <iv> -i in.aaxc -map 0:a -c copy out.m4b` |
| Decrypt time | 5.7 s | 2.9 s |
| Duration vs catalog | 1.0000 ✅ | 1.0000 ✅ |
| Audio | AAC 22.05 kHz ~63 kb/s | AAC 44.1 kHz ~126 kb/s |
| 5 s decode from the middle | ✅ | ✅ |
| Embedded chapters vs API | **20 vs 46** ⚠️ | 2 vs 2 ✅ |
| Peak disk (raw + m4b) | 523 MB ≈ **2.0×** the book | 279 MB ≈ 2.0× |

- **Private config dir works.** `AUDIBLE_CONFIG_DIR` plus a copied auth file and a minimal profile was enough for both `audible download` and `audible activation-bytes`.
- **Voucher fields:** `content_license.license_response.key` and `.iv`. The other top-level keys are `content_license.license_response.rules` and `response_groups`.
- **Quality:** `--aax -q best` returned a 22 kHz/64 k file even though that book also lists 44 kHz codecs, while the aaxc download was 44 kHz/128 k. These were **different books**, so this is a hint, not a like-for-like comparison. B5 should download one book both ways.
- **Free-space pre-flight:** require at least 2.1× `content_size_in_bytes`, which the content metadata call returns before download.

### Finding: embedded chapters can be coarser than Audible's chapter list

The `.aax` carried 20 chapters, while the API had 46. A library-wide check of all 89 books showed:
- `chapter_titles_type=Flat` always equals the **total** count of the `Tree` (89/89).
- **41 books have nested chapters** (36 multi-part, 5 single-part), for example 17 top-level / 108 total.

So the book's own chapter marks are not a reliable source.

**Proposed (G0), untested:** at decrypt time, build an ffmetadata chapter file from `<ASIN>-chapters.json` (flat), and write it with `-map_chapters` in the same `-c copy` pass, so mpv's `chapter-list` matches the phone. Fall back to the embedded chapters if the JSON is missing. B5 should test this on a nested-chapter book.

### Decision (proposed for G0): prefer aaxc, fall back to aax

Both paths work. aaxc uses a per-book key from the voucher instead of the account-wide activation bytes. Community reports say it is the format newer titles ship in (not verified here, because this library has no aaxc-only book), and it probably gives the better file. Use `--aaxc` first and fall back to `--aax` when no voucher is offered, keeping the activation-bytes path for that fallback. Confirm the quality point in B5.

---

## S3 — Position write-back ✅

**Question.** Can we write "last position heard" so other devices see it?

**Method.** Read positions for all 89 books in batches of 25. Picked the most recently updated position that was more than an hour old (so it could not be playing right now). Wrote the position minus 60 s, read it back, wrote the original value back, and read it again.

### Results

| Check | Result |
|---|---|
| Read | `GET 1.0/annotations/lastpositions?asins=…` (≤ 25): 74 `Exists`, 15 `DoesNotExist`. |
| `acr` | Comes straight from `GET 1.0/content/{asin}/metadata?response_groups=content_reference` in `content_metadata.content_reference.acr`. **No license request is needed.** |
| Write | `PUT 1.0/lastpositions/{asin}` with body `{"acr": …, "asin": …, "position_ms": …}` ✅. The response body is a string. |
| Read back | Exact (delta 0 ms), and `last_updated` changed. |
| Restore | Exact (delta 0 ms). The book stayed first in "recently listened". |
| `last_updated` format | `YYYY-MM-DD HH:MM:SS.f`, **no timezone**. Treating it as UTC gave a plausible age (3.5 h), but that is inferred. B6 should confirm it against a write made at a known time. |
| `last_updated` is UTC ✅ (B15, 2026-10-07) | Confirmed on HMSP-OMARCHYBEE during B11's acceptance: a real push read back with `position-get` had `updated_at` **about +1 s** from the UTC wall-clock time the pushed position was playing (the log's resolution; the local clock is UTC−5). |

### Phone check ✅ (2026-10-04)

`spikes/s3_phone.py` picked the most recently played unfinished book whose position was more than an hour old, moved it back **10 minutes**, and then restored it. Chris checked the Audible phone app after each write by closing and reopening the app and opening the book without pressing play.

| Check | Result |
|---|---|
| Write, then API read back | Delta 0 ms |
| Phone after the write | Showed the test position ✅ |
| Phone behavior | **The app moves to the newer position by itself and shows a notice ("moved ahead/back") with an undo option.** It doesn't ask first. Chris has never seen it ask. |
| Restore, then API read back | Delta 0 ms |
| Phone after the restore | Showed the original position again ✅ |

### Decision D4 (proposed for G0): ship position write-back

Keep the newest-wins merge from ARCHITECTURE §4.6.

**Because the phone follows a write without asking, a wrong push moves Chris's phone.** The undo on the phone limits the damage, but B6/P3 must push only positions that came from **actually listening on this machine**:
- Push on pause, stop, book switch, and drawer close, plus a slow periodic push while playing. Never push as part of `sync` or the merge.
- Never push a position that is older than the remote `last_updated` (the user listened elsewhere since).
- Never push for a book that hasn't been played locally since it was downloaded.

### Facts B6 must use

- Batch `lastpositions` at **≤ 25** ASINs, not 50.
- Get `acr` from the content metadata call, and cache it per book in `meta.json` when the book downloads.
- The write is the only mutating API call (ARCHITECTURE §4.4). The grep test must allow `PUT 1.0/lastpositions/` and nothing else.

---

## S1 — Programmatic login ✅

**Question.** Can the backend run the sign-in in two steps (build a link; finish from a pasted redirect URL) without the pasted URL touching disk or logs? Does importing an existing `~/.audible` login work?

**Method.** `spikes/s1_login.py` (subcommands `start`, `finish`, `verify`, `import`, `cleanup`) and `spikes/s1_run.sh`, run on HMSP-OMARCHYXPS on 2026-10-04 with audible 0.12.0 from the `audible-cli` uv tool venv. Chris signed in to the US store in a private Chrome window and pasted the redirect URL into a hidden prompt in a foot terminal. The scripts print booleans, counts and timings only.

### Results

| Check | Result |
|---|---|
| `start` | `audible.login.build_oauth_url(country_code, domain, market_place_id, code_verifier)` returns `(url, serial)`. `{verifier, serial, country, created}` is kept in a `0600` file under `$XDG_RUNTIME_DIR` (tmpfs), with a 10-minute TTL. No network call. ✅ |
| Sign-in | Normal Amazon sign-in in the browser. It ends on Amazon's "page not found" `…/ap/maplanding?…openid.oa2.authorization_code=…` page, as documented. The URL was 1138 characters. |
| `finish` | Parse the `openid.oa2.authorization_code` query value, then `audible.register.register(authorization_code, code_verifier, domain, serial)` (0.55 s). Build `Authenticator()`, set `locale`, `_update_attrs(with_username=False, **reg)`, `get_activation_bytes()`, `to_file(auth.json, encryption=False)`. The session file is deleted on success and on failure. ✅ |
| Files | `auth.json`, `activation_bytes`, `config.toml` all `0600`, directory `0700`. ✅ |
| New login works | `AUDIBLE_CONFIG_DIR=<dir> audible -P plugin library list` returned 91 lines (exit 0). Direct API: 91 items. ✅ |
| Activation bytes | Identical to the existing login's (they are account-wide), so books already decrypted elsewhere keep working. ✅ |
| Device | A new device (`device_type A2CZJZGLK2JJVM`, new serial). `cleanup` deregistered **only that device** (`deregister_all=False`) and the existing `~/.audible` login still worked afterward. ✅ |
| Pasted URL never persisted | The authorization code was searched for after `finish` and found in **none** of: `clipboard-history.json`, `.bash_history`, user journal, system journal (last 30 min), and the new login files. ✅ |
| Import of `~/.audible` | Validate with `Authenticator.from_file`, then copy into the private dir as `0600` and write a `plugin` profile. With `~/.audible` temporarily renamed away, `audible -P plugin library list` (91) and `audible activation-bytes` both worked from the copy alone. ✅ |
| Captcha / 2FA | Neither appeared. Amazon asked for Chris's **passkey**, which Bitwarden supplied as usual, and it worked in the private window. Every sign-in step (password, passkey, OTP, captcha) happens in the browser, and the backend only sees the final redirect URL, so none of them need backend support. |
| Marketplaces | The library has templates for 11 stores (us, uk, de, fr, ca, it, au, in, jp, es, br). Only **US** was tested. |

### Leak paths the backend and UI must close

The leak risk is in the **clipboard and the browser**, not in our code:

1. **Omarchy's clipboard history.** The shell's clipboard plugin runs `wl-paste --watch` and writes every text copy to `~/.local/state/omarchy/clipboard-history.json` (300 entries, mode 644). It skips entries when the source offers the `x-kde-passwordManagerHint` MIME type or when `CLIPBOARD_STATE=sensitive`, but a URL copied from Chrome's address bar has neither. The spike paused the watchers (`pkill -STOP`) during the paste and cleared the clipboard afterward. **The plugin can't do that.** Proposed design: the drawer has a **text field** the user pastes into with Ctrl+V. The redirect URL still passes through the clipboard and so lands in history. To avoid that, after a successful `login-finish` the backend checks for the code in clipboard history and, if found, **tells the user** (it doesn't edit a file it doesn't own). Alternatively the drawer suggests selecting the address and **dragging** it in. B3 decides; the spike shows the problem is real.
2. **Browser history.** The `maplanding` URL with the code goes into normal browser history. The code is single-use and was already redeemed, so the residual risk is low. Opening the link in a private window avoids it, but `xdg-open` can't request one. Accept it and document it.
3. **Process arguments.** ARCHITECTURE §4.2 has `login-finish --url <pasted>`, which would put the code in `/proc/<pid>/cmdline` (visible to every local user) and in any process accounting. **Proposed (G0): `login-finish` reads the URL from stdin.**
4. **The library itself.** `audible.login` and `register` don't log the URL or code. `default_login_url_callback` prints to stdout, which we don't use.

### Other findings for B3

- `~/.audible/<profile>.json` written by `audible-cli` is **mode 644** on the laptop. The import must write `0600` regardless of the source mode.
- `Authenticator.to_file` uses `write_text`, so the file mode comes from the umask. Create the file `0600` first (or set `umask 077`) instead of `chmod` afterward.
- A legacy-crypto `UserWarning` goes to stderr unless the venv installs `audible[cryptography]`. Install that extra in `setup`.
- `logout` should call `deregister_device(deregister_all=False)` before deleting files, so the device list on Amazon stays clean. It must never pass `deregister_all=True`.

### Decision

In-drawer login works. Proceed with B3 as designed, with the stdin change and the clipboard handling above. The terminal fallback is not needed.

**For D1 (license):** `finish` imports `audible` (`build_oauth_url`, `register`, `Authenticator`), and so do S2–S4. The `audible-cli` subprocess can't do the two-step login (its `quickstart` is interactive). So the backend imports an AGPL library, and **the plugin should be AGPL-3.0-only** (or AGPL-3.0-or-later). MIT would only be possible by rewriting the login and API signing ourselves.
