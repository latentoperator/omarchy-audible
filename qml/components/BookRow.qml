import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "../lib/Drawer.js" as Drawer
import "../lib/Format.js" as Format

// One Library row (FR-L6): cover, title, author, runtime, progress bar and
// state badge, a failure line for a failed download, plus Remove from
// laptop for a book on this laptop. The action icon says what a click does
// (▶ play, ⤓ download, ↻ retry), and a cloud book asks before downloading
// (`confirming`). Bind the row and the flags; `picked`, `removeRequested`,
// `confirmRequested` and `cancelRequested` go back to the view.
Rectangle {
  id: root

  property var row: null
  property bool selected: false
  property var progress: null
  property bool offline: false
  property string dataDir: ""
  property bool coverPresent: false
  property real coverVersion: 0
  property bool removable: false
  property bool removing: false
  property string iconGlyph: ""
  property string iconTooltip: ""
  property bool confirming: false
  property string questionText: ""

  signal picked()
  signal removeRequested()
  signal confirmRequested()
  signal cancelRequested()

  implicitHeight: content.implicitHeight + Style.spacing.md * 2
  radius: Style.cornerRadius
  color: selected ? Style.selectedFill : (mouse.containsMouse ? Style.hoverFill : "transparent")

  MouseArea {
    id: mouse
    anchors.fill: parent
    hoverEnabled: true
    onClicked: root.picked()
  }

  RowLayout {
    id: content
    anchors.fill: parent
    anchors.leftMargin: Style.spacing.md
    anchors.rightMargin: Style.spacing.md
    spacing: Style.spacing.lg

    Cover {
      dataDir: root.dataDir
      asin: root.row ? root.row.asin : ""
      present: root.coverPresent
      version: root.coverVersion
      size: Style.spacing.controlHeight + Style.spacing.lg * 2
    }

    ColumnLayout {
      Layout.fillWidth: true
      spacing: Style.spacing.xxs

      Text {
        Layout.fillWidth: true
        text: root.row ? root.row.title : ""
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: Color.popups.text
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }

      RowLayout {
        Layout.fillWidth: true
        spacing: Style.spacing.md

        Text {
          Layout.fillWidth: true
          text: Format.names(Drawer.authors(root.row))
          textFormat: Text.PlainText
          elide: Text.ElideRight
          // Muted is too faint for names on most themes (G3).
          color: Qt.rgba(Color.popups.text.r, Color.popups.text.g, Color.popups.text.b, 0.75)
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
        }

        Text {
          text: Format.duration(Drawer.runtimeMs(root.row))
          textFormat: Text.PlainText
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
        }
      }

      // "Download about 734 MB?" (G3 finding 3): nothing downloads until the
      // user says so here, or picks the row again.
      RowLayout {
        Layout.fillWidth: true
        visible: root.confirming
        spacing: Style.spacing.md

        Text {
          Layout.fillWidth: true
          text: root.questionText
          textFormat: Text.PlainText
          wrapMode: Text.WordWrap
          color: Color.popups.text
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
        }
        Button {
          text: "Download"
          onClicked: root.confirmRequested()
        }
        Button {
          text: "Cancel"
          onClicked: root.cancelRequested()
        }
      }

      Text {
        Layout.fillWidth: true
        visible: root.removing
        text: "Removing\u2026"
        textFormat: Text.PlainText
        color: Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }

      Text {
        Layout.fillWidth: true
        visible: text.length > 0
        text: Drawer.errorText(root.row)
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        color: Color.urgent
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }

      RowLayout {
        Layout.fillWidth: true
        spacing: Style.spacing.md

        Rectangle {
          Layout.fillWidth: true
          implicitHeight: Style.spacing.xs
          radius: height / 2
          color: Style.normalFill

          Rectangle {
            width: parent.width * Drawer.progressFraction(root.row)
            height: parent.height
            radius: parent.radius
            color: Color.accent
          }
        }

        StateBadge {
          row: root.row
          progress: root.progress
          offline: root.offline
        }
      }
    }

    PanelActionButton {
      visible: root.iconGlyph.length > 0 && !root.confirming
      iconText: root.iconGlyph
      tooltipText: root.iconTooltip
      onClicked: root.picked()
    }

    PanelActionButton {
      visible: root.removable && !root.removing
      iconText: Drawer.GLYPH_REMOVE
      tooltipText: "Remove from laptop"
      hoverColor: Color.urgent
      onClicked: root.removeRequested()
    }
  }
}
