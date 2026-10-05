import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "../components"
import "../lib/Format.js" as Format
import "../lib/Mini.js" as Mini
import "../lib/Panel.js" as Panel

// Minimal Mini view (U2a): cover, title, author, elapsed and remaining time,
// ⏪15 ⏯ ⏩15 and a library button. U5 extends this file with the scrub
// bar, chapters, speed, maximize and dismiss.
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

  spacing: Style.spacing.panelGap

  RowLayout {
    Layout.fillWidth: true
    spacing: Style.spacing.xl

    Cover {
      dataDir: root.service ? root.service.dataDir : ""
      asin: root.asin
      present: root.library ? root.library.hasCover(root.asin) : false
      version: root.library ? root.library.coverVersion(root.asin) : 0
      size: Style.spacing.controlHeight * 2
    }

    ColumnLayout {
      Layout.fillWidth: true
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

      Text {
        Layout.fillWidth: true
        readonly property var names: Mini.authors(root.loaded, root.row)
        visible: names.length > 0
        text: Format.names(names)
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }
    }
  }

  RowLayout {
    Layout.fillWidth: true
    visible: root.loaded

    Text {
      text: Format.clock(root.positionMs)
      textFormat: Text.PlainText
      color: Color.popups.text
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }

    Item { Layout.fillWidth: true }

    Text {
      text: "−" + Format.clock(Mini.remainingMs(root.positionMs, root.durationMs))
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }
  }

  RowLayout {
    Layout.fillWidth: true
    spacing: Style.spacing.controlGap

    Button {
      enabled: root.loaded
      iconText: Mini.GLYPH_BACK
      text: String(Mini.SKIP_SECONDS)
      tooltipText: "Back " + Mini.SKIP_SECONDS + " s (←)"
      onClicked: root.player.skip(Mini.skipSeconds(Mini.ACTION_BACK))
    }

    Button {
      enabled: root.loaded
      iconText: Mini.playGlyph(root.player ? root.player.playing : false)
      tooltipText: "Play / pause (Space)"
      onClicked: root.player.toggle()
    }

    Button {
      enabled: root.loaded
      iconText: Mini.GLYPH_FORWARD
      text: String(Mini.SKIP_SECONDS)
      tooltipText: "Forward " + Mini.SKIP_SECONDS + " s (→)"
      onClicked: root.player.skip(Mini.skipSeconds(Mini.ACTION_FORWARD))
    }

    Item { Layout.fillWidth: true }

    Button {
      iconText: Mini.GLYPH_LIBRARY
      tooltipText: "Library"
      onClicked: if (root.service) root.service.showView(Panel.VIEW_LIBRARY)
    }
  }
}
