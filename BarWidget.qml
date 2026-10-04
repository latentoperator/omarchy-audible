import QtQuick
import Quickshell
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "latentoperator.audible"

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "\uf02d"
    fontFamily: root.bar ? root.bar.fontFamily : Style.font.family
    horizontalMargin: 6
    tooltipText: "Omarchy Audible"
  }
}
