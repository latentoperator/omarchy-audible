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

## S3 — Position write-back ✅ (API level; phone check pending)

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

**Not yet done:** confirming in the Audible phone app. The API round trip is exact, but the plan asks for a phone check. It takes Chris one minute: move one book by a known amount, then look at the phone.

### Decision D4 (proposed for G0): ship position write-back

Keep the newest-wins merge from ARCHITECTURE §4.6. If the phone check fails, fall back to read-only sync, as the plan already allows.

### Facts B6 must use

- Batch `lastpositions` at **≤ 25** ASINs, not 50.
- Get `acr` from the content metadata call, and cache it per book in `meta.json` when the book downloads.
- The write is the only mutating API call (ARCHITECTURE §4.4). The grep test must allow `PUT 1.0/lastpositions/` and nothing else.

---

## S1 — Programmatic login

Not started. It needs Chris to sign in through a browser and paste the redirect URL into the drawer.
