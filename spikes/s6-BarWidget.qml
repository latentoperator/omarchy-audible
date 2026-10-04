import QtQuick
import Quickshell
import qs.Commons
import qs.Ui

// S6 spike: book glyph that toggles an anchored, themed drawer.
// The drawer is a qs.Ui KeyboardPanel owned by this widget (the same pattern
// as the stock audio panel and the Spotify mini player). It closes on Esc,
// click-away, or when another bar popout opens.
BarWidget {
  id: root
  moduleName: "latentoperator.audible"

  readonly property var service: bar && bar.shell
    ? bar.shell.serviceFor("latentoperator.audible") : null

  property bool opened: false
  property bool popoutSwitchClosing: false

  function open() { opened = true }
  function close() { opened = false }
  function toggle() { opened ? close() : open() }
  function closeForPopoutSwitch() {
    popoutSwitchClosing = true
    close()
    Qt.callLater(function() { root.popoutSwitchClosing = false })
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onServiceChanged: if (service) service.registerSurface(root)
  Component.onCompleted: if (service) service.registerSurface(root)
  Component.onDestruction: if (service) service.unregisterSurface(root)

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "\uf02d"
    tooltipText: "Omarchy Audible"
    onPressed: function(b) { root.toggle() }
  }

  KeyboardPanel {
    id: popup
    anchorItem: button
    bar: root.bar
    owner: root
    open: root.opened
    focusTarget: keys
    contentWidth: fittedContentWidth(Style.space(380))
    contentHeight: fittedContentHeight(content.implicitHeight, Style.space(560))

    PanelKeyCatcher {
      id: keys
      anchors.fill: parent
      onCloseRequested: root.close()

      Column {
        id: content
        width: parent.width
        spacing: Style.spacing.md

        Text {
          text: "Omarchy Audible"
          color: Color.popups.text
          font.family: Style.font.family
          font.pixelSize: Style.font.heading
        }

        Text {
          width: parent.width
          wrapMode: Text.WordWrap
          text: "Your library will appear here. Esc or click away to close."
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }
      }
    }
  }
}
