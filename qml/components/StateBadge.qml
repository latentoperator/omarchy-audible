import QtQuick
import qs.Commons
import "../lib/LibraryUi.js" as LibraryUi
import "../lib/Parts.js" as Parts

// A row's state badge (FR-L6): the kind and label from `LibraryUi.badge`,
// coloured by `Parts.badgeTone`. Bind `row`, the running `get` event as
// `progress`, and `offline`.
Rectangle {
  id: root

  property var row: null
  property var progress: null
  property bool offline: false

  readonly property var badge: LibraryUi.badge(row, progress, offline)
  readonly property string kind: badge.kind
  readonly property string label: badge.label
  readonly property string tone: Parts.badgeTone(kind)
  readonly property color toneColor: tone === Parts.TONE_ACCENT ? Color.accent
    : tone === Parts.TONE_URGENT ? Color.urgent
    : tone === Parts.TONE_TEXT ? Color.popups.text
    : Color.muted

  implicitWidth: text.implicitWidth + Style.spacing.lg * 2
  implicitHeight: text.implicitHeight + Style.spacing.xs * 2
  radius: Math.min(Style.cornerRadius, Math.floor(implicitHeight / 2))
  color: Util.alpha(toneColor, Style.selectedFillAlpha)
  border.width: Style.normalBorderWidth
  border.color: Util.alpha(toneColor, Style.normalBorderAlpha)

  Text {
    id: text
    anchors.centerIn: parent
    text: root.label
    color: root.toneColor
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
  }
}
