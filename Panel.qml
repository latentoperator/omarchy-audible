import QtQuick
import Quickshell
import qs.Commons
import qs.Ui

// Themed empty placeholder. Later tasks host the Library/Mini/Full views here.
Item {
  id: root

  property var shell: null
  property var manifest: null
  property var service: null
  property bool opened: false

  Rectangle {
    anchors.fill: parent
    color: Color.background
  }
}
