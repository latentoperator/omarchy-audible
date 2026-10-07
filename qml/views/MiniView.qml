import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "../components"
import "../lib/Format.js" as Format
import "../lib/Mini.js" as Mini
import "../lib/Panel.js" as Panel
import "../lib/Player.js" as Player

// Mini view (FR-U3): cover, title, author, the current chapter with a chapter
// popup, the scrub bar, ⏮ ⏪N ⏯ ⏩N ⏭, the speed pill, maximize, library and
// dismiss. Dismissing only hides the panel; playback carries on.
ColumnLayout {
  id: root

  property var service: null
  // This view's own panel is open (BarWidget binds it). Each monitor has a
  // Mini view; only the open one shows the chapter popup (H1 F25).
  property bool panelOpen: false

  readonly property var player: service ? service.player : null
  readonly property var library: service ? service.library : null
  readonly property bool loaded: player ? player.loaded : false
  readonly property var row: service ? service.loadedRow : null
  readonly property string asin: service ? service.loadedAsin : ""
  readonly property var chapters: player ? player.chapters : []
  readonly property int chapterIndex: player ? player.chapterIndex : -1
  readonly property string chapterText: Player.chapterLabel(chapters, chapterIndex)
  // ⏯ is reading the account before it resumes.
  readonly property bool checking: service ? service.catchupAsin.length > 0 : false

  signal closeRequested()
  // The chapter popup closed: the panel's key catcher takes the keys back.
  signal keysReleased()

  spacing: Style.spacing.panelGap

  readonly property bool chapterPopupShown: Panel.chapterPopupShown(
    service ? service.chapterListOpen : false, panelOpen)
  onChapterPopupShownChanged: chapterPopupShown ? chapterMenu.open() : chapterMenu.close()

  RowLayout {
    Layout.fillWidth: true
    spacing: Style.spacing.xl

    Cover {
      Layout.alignment: Qt.AlignTop
      dataDir: root.service ? root.service.dataDir : ""
      asin: root.asin
      present: root.library ? root.library.hasCover(root.asin) : false
      version: root.library ? root.library.coverVersion(root.asin) : 0
      size: Style.spacing.controlHeight * 2
    }

    ColumnLayout {
      Layout.fillWidth: true
      Layout.alignment: Qt.AlignTop
      spacing: Style.spacing.labelGap

      Text {
        Layout.fillWidth: true
        text: Mini.title(root.loaded, root.row)
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: Color.popups.text
        font.family: Style.font.family
        font.pixelSize: Style.font.title
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
    }

    // A sleep timer is set (FR-U4: Mini shows only this glyph).
    Text {
      Layout.alignment: Qt.AlignTop
      Layout.topMargin: Style.spacing.controlPaddingY
      visible: root.player ? root.player.sleepTimer !== null : false
      text: Player.GLYPH_MOON
      textFormat: Text.PlainText
      color: Color.popups.text
      font.family: Style.font.family
      font.pixelSize: Style.font.iconSmall
    }

    Button {
      Layout.alignment: Qt.AlignTop
      enabled: root.loaded
      iconText: Player.GLYPH_MAXIMIZE
      tooltipText: "Full player"
      onClicked: if (root.service) root.service.showView(Panel.VIEW_FULL)
    }

    Button {
      Layout.alignment: Qt.AlignTop
      iconText: Player.GLYPH_DISMISS
      tooltipText: "Close (Esc)"
      onClicked: root.closeRequested()
    }
  }

  // The current chapter; a click lists them all.
  BorderSurface {
    id: chapterLine
    Layout.fillWidth: true
    visible: root.loaded && root.chapterText.length > 0
    implicitHeight: Style.spacing.controlHeight
    radius: Style.cornerRadius
    color: chapterMouse.pressed ? Style.pressedFillFor(Color.popups.text, Color.accent)
      : chapterMouse.containsMouse || chapterMenu.opened ? Style.hoverFillFor(Color.popups.text, Color.accent)
      : "transparent"

    RowLayout {
      anchors.fill: parent
      anchors.leftMargin: Style.spacing.controlPaddingX
      anchors.rightMargin: Style.spacing.controlPaddingX
      spacing: Style.spacing.controlGap

      Text {
        text: Player.GLYPH_CHAPTERS
        textFormat: Text.PlainText
        color: Color.popups.text
        font.family: Style.font.family
        font.pixelSize: Style.font.iconSmall
      }

      Text {
        Layout.fillWidth: true
        text: root.chapterText
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: Color.popups.text
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }
    }

    MouseArea {
      id: chapterMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      // While the popup is open it is modal, so this line never sees the press.
      onClicked: if (root.service) root.service.chapterListOpen = true
    }
  }

  ChapterMenu {
    id: chapterMenu
    Layout.fillWidth: true
    Layout.topMargin: opened ? 0 : -root.spacing
    rows: Player.chapterRows(root.chapters, root.player ? root.player.durationMs : 0)
    currentIndex: root.chapterIndex
    onChosen: function(index) { root.player.setChapter(index) }
    onClosed: {
      if (root.service) root.service.chapterListOpen = false
      root.keysReleased()
    }
  }

  ScrubBar {
    Layout.fillWidth: true
    visible: root.loaded
    enabled: root.loaded
    positionMs: root.player ? root.player.positionMs : 0
    durationMs: root.player ? root.player.durationMs : 0
    chapters: root.chapters
    restarts: root.player ? root.player.restarts : 0
    note: root.checking ? "Checking Audible…" : ""
    onSeekRequested: function(ms) { root.player.seekMs(ms) }
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

  // Pushes keep coming back `stale`: the position isn't reaching Audible (P6).
  SoftText {
    Layout.fillWidth: true
    visible: text.length > 0
    text: root.service ? root.service.staleNotice : ""
    textFormat: Text.PlainText
    wrapMode: Text.WordWrap
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
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

  RowLayout {
    Layout.fillWidth: true
    spacing: Style.spacing.xs

    TransportRow {
      service: root.service
    }

    Item { Layout.fillWidth: true }

    Button {
      enabled: root.loaded
      bordered: true
      text: Player.speedLabel(root.player ? root.player.speed : 1)
      tooltipText: "Speed: click for the next preset"
      onClicked: root.player.setSpeed(Player.nextSpeed(root.player.speed))
    }

    Button {
      iconText: Mini.GLYPH_LIBRARY
      tooltipText: "Library"
      onClicked: if (root.service) root.service.showView(Panel.VIEW_LIBRARY)
    }
  }
}
