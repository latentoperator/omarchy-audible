import QtQuick
import QtQuick.Effects
import qs.Commons
import "../lib/Parts.js" as Parts
import "../lib/Panel.js" as Panel

// A book's cover, always square. Loads `<dataDir>/covers/<asin>.jpg` off the
// UI thread; until it is ready, or when it is missing or broken, shows the
// book glyph on a themed tile. Corners follow the theme's rounding.
// Bind `present` to `service.library.hasCover(asin)`, so a file that is not
// there is never requested and a missing cover logs nothing, and `version`
// to `service.library.coverVersion(asin)`, so a replaced file is reloaded.
Item {
  id: root

  property string dataDir: ""
  property string asin: ""
  property bool present: false
  property real version: 0
  property int size: Style.spacing.controlHeight * 2

  readonly property string source: present ? Parts.coverUrl(dataDir, asin, version) : ""
  readonly property bool loaded: image.status === Image.Ready
  readonly property int radius: Math.min(Style.cornerRadius, Math.floor(size / 4))

  implicitWidth: size
  implicitHeight: size
  width: size
  height: size
  clip: true

  Rectangle {
    id: tile
    anchors.fill: parent
    radius: root.radius
    visible: !root.loaded
    color: Style.normalFill
    border.width: Style.normalBorderWidth
    border.color: Style.normalBorderColor

    Text {
      anchors.centerIn: parent
      text: Panel.GLYPH_BOOK
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.iconLarge
    }
  }

  Rectangle {
    id: mask
    anchors.fill: parent
    radius: root.radius
    visible: false
    layer.enabled: true
    color: "white"
  }

  Image {
    id: image
    anchors.fill: parent
    visible: root.loaded
    source: root.source
    asynchronous: true
    cache: true
    fillMode: Image.PreserveAspectCrop
    clip: true
    sourceSize.width: root.size
    sourceSize.height: root.size
    smooth: true
    layer.enabled: root.loaded && root.radius > 0
    layer.smooth: true
    layer.effect: MultiEffect {
      maskEnabled: true
      maskSource: mask
      maskThresholdMin: 0.3
      maskSpreadAtMin: 0.3
    }
  }
}
