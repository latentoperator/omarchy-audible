pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import qs.Commons
import "../lib/Format.js" as Format
import "../lib/Mini.js" as Mini
import "../lib/Player.js" as Player

// Book-level scrub bar with elapsed time on the left and time left on the
// right (FR-U3, FR-P3). While the pointer is down the handle follows it and
// ignores `positionMs`; release seeks once, and the bar shows the target
// until the player reports a position near it, so the handle never jumps
// back to the old spot.
ColumnLayout {
  id: root

  property int positionMs: 0
  property int durationMs: 0
  property var chapters: []
  // PlayerController.restarts: counts mpv's playback-restart events.
  property int restarts: 0
  // Replaces the time-left text while set ("Checking Audible…").
  property string note: ""

  signal seekRequested(int ms)

  property bool dragging: false
  property real dragFraction: 0
  property int pendingMs: -1
  // `restarts` when the drag ended (see `Player.seekSettled`).
  property int pendingRestarts: 0

  readonly property int shownMs: dragging ? Player.positionAt(dragFraction, durationMs)
    : (pendingMs >= 0 ? pendingMs : positionMs)
  readonly property real shownFraction: dragging ? dragFraction : Player.fraction(shownMs, durationMs)
  readonly property var ticks: Player.tickFractions(chapters, durationMs)

  spacing: Style.spacing.xxs

  function checkSettled() {
    if (pendingMs >= 0 && Player.seekSettled(positionMs, pendingMs, pendingRestarts, restarts)) pendingMs = -1
  }
  onPositionMsChanged: checkSettled()
  onRestartsChanged: checkSettled()

  // The player never reported the target (paused far away, or the seek was
  // refused): stop holding it.
  Timer {
    id: settleTimer
    interval: 3000
    onTriggered: root.pendingMs = -1
  }

  Item {
    id: bar
    Layout.fillWidth: true
    implicitHeight: Math.max(Style.space(22), knob.height + Style.spacing.md)

    readonly property real trackHeight: Math.max(Style.space(4), Math.round(Style.spacing.controlHeight * 0.11))
    readonly property bool hot: mouse.containsMouse || root.dragging

    Rectangle {
      id: track
      anchors.verticalCenter: parent.verticalCenter
      anchors.left: parent.left
      anchors.right: parent.right
      height: bar.trackHeight
      radius: height / 2
      color: Style.normalFill
    }

    Rectangle {
      anchors.verticalCenter: track.verticalCenter
      anchors.left: track.left
      height: track.height
      radius: track.radius
      width: track.width * root.shownFraction
      color: Color.accent
    }

    // Chapter starts, cut into the track in the panel's background color.
    Repeater {
      model: root.ticks
      Rectangle {
        required property real modelData
        width: Math.max(1, Style.space(2))
        height: track.height
        color: Color.popups.background
        anchors.verticalCenter: track.verticalCenter
        x: Math.round(track.width * modelData - width / 2)
      }
    }

    Rectangle {
      id: knob
      readonly property real size: Math.max(Style.space(12), Math.round(Style.spacing.controlHeight * 0.38))
      width: size
      height: size
      radius: size / 2
      visible: root.enabled && root.durationMs > 0
      color: Color.accent
      border.color: Color.popups.background
      border.width: Math.max(1, Style.space(2))
      anchors.verticalCenter: track.verticalCenter
      x: Math.max(0, Math.min(track.width - width, track.width * root.shownFraction - width / 2))
      scale: bar.hot ? 1.15 : 1.0
      Behavior on scale { NumberAnimation { duration: 110; easing.type: Easing.OutCubic } }
    }

    MouseArea {
      id: mouse
      anchors.fill: parent
      enabled: root.enabled && root.durationMs > 0
      hoverEnabled: true
      preventStealing: true
      cursorShape: Qt.PointingHandCursor

      function fractionAt(x) { return Math.max(0, Math.min(1, x / Math.max(1, track.width))) }

      onPressed: function(event) {
        root.dragFraction = fractionAt(event.x)
        root.dragging = true
      }
      onPositionChanged: function(event) {
        if (root.dragging) root.dragFraction = fractionAt(event.x)
      }
      onReleased: function(event) {
        if (!root.dragging) return
        root.dragFraction = fractionAt(event.x)
        var ms = Player.positionAt(root.dragFraction, root.durationMs)
        root.pendingRestarts = root.restarts
        root.pendingMs = ms
        root.dragging = false
        settleTimer.restart()
        root.seekRequested(ms)
      }
      // A grab taken away mid-drag is not a seek.
      onCanceled: root.dragging = false
    }
  }

  RowLayout {
    Layout.fillWidth: true

    Text {
      text: Format.clock(root.shownMs)
      textFormat: Text.PlainText
      color: Color.popups.text
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }

    Item { Layout.fillWidth: true }

    Text {
      text: root.note.length > 0 ? root.note
        : "−" + Format.clock(Mini.remainingMs(root.shownMs, root.durationMs))
      textFormat: Text.PlainText
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }
  }
}
