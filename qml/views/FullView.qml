pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "../components"
import "../lib/Drawer.js" as Drawer
import "../lib/Format.js" as Format
import "../lib/Glyphs.js" as Glyphs
import "../lib/Mini.js" as Mini
import "../lib/Mpv.js" as Mpv
import "../lib/Panel.js" as Panel
import "../lib/Player.js" as Player

// Full view (FR-U4): large cover, title, author, narrators and details, the
// scrub bar and transport shared with Mini, speed presets and fine control,
// the sleep timer, the chapter list, Remove from this device, collapse and
// dismiss. It grows the same drawer; there is no second window.
ColumnLayout {
  id: root

  property var service: null

  readonly property var player: service ? service.player : null
  readonly property var library: service ? service.library : null
  readonly property bool loaded: player ? player.loaded : false
  readonly property var row: service ? service.loadedRow : null
  readonly property string asin: service ? service.loadedAsin : ""
  readonly property int positionMs: player ? player.positionMs : 0
  readonly property int durationMs: player ? player.durationMs : 0
  readonly property real speed: player ? player.speed : 1
  readonly property var sleepTimer: player ? player.sleepTimer : null
  readonly property bool checking: service ? service.catchupAsin.length > 0 : false
  readonly property var narratorNames: Player.narrators(row)

  // Ticks once a second while a sleep timer counts down on screen.
  property real nowMs: Date.now()
  property bool confirmRemove: false

  signal closeRequested()

  spacing: Style.spacing.panelGap

  onVisibleChanged: {
    confirmRemove = false
    if (visible) chapterList.reveal()
  }
  onAsinChanged: confirmRemove = false

  Timer {
    interval: 1000
    repeat: true
    running: root.visible && root.sleepTimer !== null
    triggeredOnStart: true
    onTriggered: root.nowMs = Date.now()
  }

  // ---- header ----
  RowLayout {
    Layout.fillWidth: true
    spacing: Style.spacing.xl

    Cover {
      Layout.alignment: Qt.AlignTop
      dataDir: root.service ? root.service.dataDir : ""
      asin: root.asin
      present: root.library ? root.library.hasCover(root.asin) : false
      version: root.library ? root.library.coverVersion(root.asin) : 0
      size: Style.space(160)
    }

    ColumnLayout {
      Layout.fillWidth: true
      Layout.alignment: Qt.AlignTop
      spacing: Style.spacing.labelGap

      Text {
        Layout.fillWidth: true
        text: Mini.title(root.loaded, root.row)
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        maximumLineCount: 2
        elide: Text.ElideRight
        color: Color.popups.text
        font.family: Style.font.family
        font.pixelSize: Style.font.heading
        font.bold: true
      }

      SoftText {
        Layout.fillWidth: true
        readonly property var names: Mini.authors(root.loaded, root.row)
        visible: names.length > 0
        text: Format.names(names)
        textFormat: Text.PlainText
        elide: Text.ElideRight
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }

      SoftText {
        Layout.fillWidth: true
        visible: root.narratorNames.length > 0
        text: "Narrated by " + Format.names(root.narratorNames)
        textFormat: Text.PlainText
        elide: Text.ElideRight
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }

      Item { implicitHeight: Style.spacing.sm }

      Text {
        Layout.fillWidth: true
        visible: root.loaded && root.durationMs > 0
        text: Format.duration(root.durationMs) + " · "
          + Player.percentComplete(root.positionMs, root.durationMs) + "% complete"
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: Color.popups.text
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }

      Text {
        Layout.fillWidth: true
        visible: root.loaded && root.durationMs > 0
        text: Format.duration(Player.leftAtSpeedMs(root.positionMs, root.durationMs, root.speed))
          + " left at " + Player.speedLabel(root.speed)
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: Color.popups.text
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }

      // Why the position just moved: a catch-up jump to another device's spot.
      SoftText {
        Layout.fillWidth: true
        visible: text.length > 0
        text: root.service ? root.service.catchupNote : ""
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }
    }

    RowLayout {
      Layout.alignment: Qt.AlignTop
      spacing: Style.spacing.xxs

      // The same Library button as Mini's (U8); playback carries on.
      Button {
        iconText: Glyphs.GLYPH_LIBRARY
        tooltipText: "Library"
        onClicked: if (root.service) root.service.showView(Panel.VIEW_LIBRARY)
      }

      Button {
        iconText: Glyphs.GLYPH_COLLAPSE
        tooltipText: "Mini player (Backspace)"
        onClicked: if (root.service) root.service.showView(Panel.VIEW_MINI)
      }

      Button {
        iconText: Glyphs.GLYPH_DISMISS
        tooltipText: "Close (Esc)"
        onClicked: root.closeRequested()
      }
    }
  }

  // A play that never started (G3 finding 2).
  Text {
    Layout.fillWidth: true
    visible: root.service ? root.service.playFailure.length > 0 : false
    text: "Couldn't start playback: " + (root.service ? root.service.playFailure : "")
    textFormat: Text.PlainText
    wrapMode: Text.WordWrap
    color: Color.urgent
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
  }

  // ---- position and transport ----
  ScrubBar {
    Layout.fillWidth: true
    visible: root.loaded
    enabled: root.loaded
    positionMs: root.positionMs
    durationMs: root.durationMs
    chapters: root.player ? root.player.chapters : []
    restarts: root.player ? root.player.restarts : 0
    note: root.checking ? "Checking Audible…" : ""
    onSeekRequested: function(ms) { root.player.seekMs(ms) }
  }

  TransportRow {
    Layout.alignment: Qt.AlignHCenter
    service: root.service
  }

  // ---- speed ----
  RowLayout {
    Layout.fillWidth: true
    spacing: Style.spacing.xs

    Text {
      Layout.preferredWidth: Style.space(52)
      text: "Speed"
      textFormat: Text.PlainText
      color: Color.popups.text
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
      font.bold: true
    }

    Repeater {
      model: Player.SPEED_PRESETS
      Button {
        required property real modelData
        enabled: root.loaded
        text: Player.speedLabel(modelData)
        fontSize: Style.font.bodySmall
        horizontalPadding: Style.spacing.md
        selected: Player.isSpeed(root.speed, modelData)
        onClicked: root.player.setSpeed(modelData)
      }
    }

    Item { Layout.fillWidth: true }

    Button {
      enabled: root.loaded && Player.canFineStep(root.speed, -1)
      iconText: Glyphs.GLYPH_SLOWER
      iconSize: Style.font.iconSmall
      tooltipText: "Slower (−0.05)"
      onClicked: root.player.setSpeed(Player.fineSpeed(root.speed, -1))
    }

    Text {
      Layout.minimumWidth: Style.space(44)
      horizontalAlignment: Text.AlignHCenter
      text: Player.speedLabel(root.speed)
      textFormat: Text.PlainText
      color: Color.popups.text
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }

    Button {
      enabled: root.loaded && Player.canFineStep(root.speed, 1)
      iconText: Glyphs.GLYPH_FASTER
      iconSize: Style.font.iconSmall
      tooltipText: "Faster (+0.05)"
      onClicked: root.player.setSpeed(Player.fineSpeed(root.speed, 1))
    }
  }

  // ---- sleep timer ----
  RowLayout {
    Layout.fillWidth: true
    spacing: Style.spacing.xs

    Text {
      Layout.preferredWidth: Style.space(52)
      text: "Sleep"
      textFormat: Text.PlainText
      color: Color.popups.text
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
      font.bold: true
    }

    Repeater {
      model: Player.SLEEP_MINUTES
      Button {
        required property int modelData
        enabled: root.loaded
        text: modelData + " min"
        fontSize: Style.font.bodySmall
        horizontalPadding: Style.spacing.md
        onClicked: root.player.setSleepTimer(modelData)
      }
    }

    Button {
      enabled: root.loaded && Mpv.chapterEndMs(root.player.chapters, root.player.chapterIndex, root.durationMs) >= 0
      text: "End of chapter"
      fontSize: Style.font.bodySmall
      horizontalPadding: Style.spacing.md
      onClicked: root.player.setSleepEndOfChapter()
    }

    Item { Layout.fillWidth: true }

    Text {
      visible: root.sleepTimer !== null
      text: Glyphs.GLYPH_MOON + "  " + Player.sleepText(root.sleepTimer,
        Mpv.sleepRemainingMs(root.sleepTimer, root.nowMs, root.positionMs, root.speed))
      textFormat: Text.PlainText
      color: Color.popups.text
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }

    Button {
      visible: root.sleepTimer !== null
      text: "Cancel"
      fontSize: Style.font.bodySmall
      bordered: true
      onClicked: root.player.cancelSleep()
    }
  }

  // ---- chapters ----
  Text {
    text: "Chapters"
    textFormat: Text.PlainText
    color: Color.popups.text
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
    font.bold: true
  }

  ChapterList {
    id: chapterList
    Layout.fillWidth: true
    Layout.preferredHeight: Math.max(1, Math.min(count, 8)) * Style.spacing.popupRowHeight
    rows: Player.chapterRows(root.player ? root.player.chapters : [], root.durationMs)
    currentChapter: root.player ? root.player.chapterIndex : -1
    onChosen: function(index) { root.player.setChapter(index) }
  }

  // ---- remove ----
  RowLayout {
    Layout.fillWidth: true
    spacing: Style.spacing.controlGap

    Button {
      visible: !root.confirmRemove
      enabled: Drawer.canRemove(root.row)
      iconText: Glyphs.GLYPH_REMOVE
      text: "Remove from this device"
      bordered: true
      onClicked: root.confirmRemove = true
    }

    Text {
      Layout.fillWidth: true
      visible: root.confirmRemove
      text: "Remove this book from this device? It stays in your library."
      textFormat: Text.PlainText
      wrapMode: Text.WordWrap
      color: Color.popups.text
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }

    Button {
      visible: root.confirmRemove
      text: "Remove"
      bordered: true
      onClicked: {
        root.confirmRemove = false
        root.service.removeBook(root.asin)
        root.service.showView(Panel.VIEW_LIBRARY)
      }
    }

    Button {
      visible: root.confirmRemove
      text: "Cancel"
      onClicked: root.confirmRemove = false
    }
  }
}
