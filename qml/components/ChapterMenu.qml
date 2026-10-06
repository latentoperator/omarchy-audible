pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Ui
import "../lib/Format.js" as Format

// The Mini view's chapter popup: every chapter with its start time, the
// current one highlighted and scrolled into view. Choosing a row, Esc or a
// click outside it closes it; the panel stays open.
//
// The panel window is only as tall as the view, so the popup sits on this
// item, which takes the popup's height in the layout while it is open and
// grows the panel with it.
Item {
  id: root

  // `Player.chapterRows` output.
  property var rows: []
  property int currentIndex: -1
  property int visibleRows: 8

  readonly property bool opened: popup.opened
  readonly property real listHeight: Math.min(rows.length, visibleRows) * Style.spacing.popupRowHeight
    + Border.top(popupBorder) + Border.bottom(popupBorder) + Style.spacing.hairline * 2
  readonly property var popupBorder: Border.localOrSurfaceSpec("popups", "border", Color.popups.border,
    Color.popups.border, Style.normalBorderWidth)

  signal chosen(int index)
  signal closed()

  function open() { if (rows.length > 0) popup.open() }
  function close() { popup.close() }

  implicitHeight: popup.opened ? listHeight : 0

  Popup {
    id: popup
    x: 0
    y: 0
    width: root.width
    height: root.listHeight
    padding: Style.spacing.hairline
    leftPadding: Border.left(root.popupBorder) + Style.spacing.hairline
    rightPadding: Border.right(root.popupBorder) + Style.spacing.hairline
    topPadding: Border.top(root.popupBorder) + Style.spacing.hairline
    bottomPadding: Border.bottom(root.popupBorder) + Style.spacing.hairline
    focus: true
    // Modal without a dim: a press outside only closes the popup. A
    // non-modal popup would let it through to the panel's own dismissal
    // area, closing the panel too.
    modal: true
    dim: false
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    background: BorderSurface {
      color: Color.popups.background
      borderSpec: root.popupBorder
      radius: Style.cornerRadius
    }

    onOpened: {
      list.currentIndex = Math.max(0, root.currentIndex)
      list.positionViewAtIndex(list.currentIndex, ListView.Center)
      list.forceActiveFocus()
    }
    onClosed: root.closed()

    contentItem: ListView {
      id: list
      clip: true
      boundsBehavior: Flickable.StopAtBounds
      model: root.rows
      currentIndex: -1
      highlightMoveDuration: 0

      function choose(index) {
        if (index < 0 || index >= root.rows.length) return
        popup.close()
        root.chosen(index)
      }

      Keys.priority: Keys.BeforeItem
      Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Escape) popup.close()
        else if (event.key === Qt.Key_Down) list.currentIndex = Math.min(root.rows.length - 1, list.currentIndex + 1)
        else if (event.key === Qt.Key_Up) list.currentIndex = Math.max(0, list.currentIndex - 1)
        else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) list.choose(list.currentIndex)
        else return
        event.accepted = true
      }

      delegate: Rectangle {
        id: row
        required property var modelData
        required property int index
        readonly property bool current: index === root.currentIndex
        readonly property bool hot: index === list.currentIndex

        width: list.width
        height: Style.spacing.popupRowHeight
        color: hot ? Style.hoverFillFor(Color.popups.text, Color.accent)
          : current ? Style.selectedFillFor(Color.popups.text, Color.accent)
          : "transparent"

        Text {
          anchors.left: parent.left
          anchors.right: start.left
          anchors.verticalCenter: parent.verticalCenter
          anchors.leftMargin: Style.spacing.controlPaddingX
          anchors.rightMargin: Style.spacing.controlGap
          text: row.modelData.label
          textFormat: Text.PlainText
          elide: Text.ElideRight
          color: row.hot ? Style.hoverStateColor(Color.popups.text, Color.accent)
            : row.current ? Style.selectedStateColor(Color.popups.text, Color.accent)
            : Color.popups.text
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          font.bold: row.current
        }

        Text {
          id: start
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          anchors.rightMargin: Style.spacing.controlPaddingX
          text: Format.clock(row.modelData.startMs)
          textFormat: Text.PlainText
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
        }

        MouseArea {
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onEntered: list.currentIndex = row.index
          onClicked: list.choose(row.index)
        }
      }
    }
  }
}
