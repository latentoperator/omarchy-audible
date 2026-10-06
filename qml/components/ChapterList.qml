pragma ComponentBehavior: Bound

import QtQuick
import qs.Commons
import "../lib/Format.js" as Format
import "../lib/Player.js" as Player

// The Full view's chapter list (FR-U4): titles and durations, the current
// chapter highlighted, a click jumps to it. It follows the current chapter
// when shown and when the chapter changes, unless the user scrolled it in
// the last few seconds. Rows are delegates, built only as they scroll in.
ListView {
  id: root

  // `Player.chapterRows` output.
  property var rows: []
  property int currentChapter: -1
  // When the user last scrolled the list (start or end of the gesture).
  property real userScrolledAtMs: 0

  signal chosen(int index)

  function follow(force) {
    if (currentChapter < 0 || currentChapter >= count) return
    if (force || Player.followChapter(Date.now(), userScrolledAtMs, moving)) positionViewAtIndex(currentChapter, ListView.Center)
  }

  // Shown: a fresh look, so follow even after an old scroll.
  function reveal() {
    userScrolledAtMs = 0
    Qt.callLater(function() { root.follow(true) })
  }

  clip: true
  boundsBehavior: Flickable.StopAtBounds
  model: rows
  reuseItems: true

  onCurrentChapterChanged: follow(false)
  onCountChanged: Qt.callLater(function() { root.follow(false) })
  // Only the user moves the list (positionViewAtIndex doesn't), so the
  // hold counts from the end of their last scroll.
  onMovementStarted: userScrolledAtMs = Date.now()
  onMovementEnded: userScrolledAtMs = Date.now()

  delegate: Rectangle {
    id: row
    required property var modelData
    required property int index
    readonly property bool current: index === root.currentChapter

    width: root.width
    height: Style.spacing.popupRowHeight
    color: mouse.containsMouse ? Style.hoverFillFor(Color.popups.text, Color.accent)
      : current ? Style.selectedFillFor(Color.popups.text, Color.accent)
      : "transparent"

    Text {
      anchors.left: parent.left
      anchors.right: length.left
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.spacing.controlPaddingX
      anchors.rightMargin: Style.spacing.controlGap
      text: row.modelData.label
      textFormat: Text.PlainText
      elide: Text.ElideRight
      color: mouse.containsMouse ? Style.hoverStateColor(Color.popups.text, Color.accent)
        : row.current ? Style.selectedStateColor(Color.popups.text, Color.accent)
        : Color.popups.text
      font.family: Style.font.family
      font.pixelSize: Style.font.body
      font.bold: row.current
    }

    Text {
      id: length
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.rightMargin: Style.spacing.controlPaddingX
      text: Format.clock(row.modelData.durationMs)
      textFormat: Text.PlainText
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }

    MouseArea {
      id: mouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: root.chosen(row.index)
    }
  }
}
