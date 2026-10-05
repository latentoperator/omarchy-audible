import QtQuick
import QtQuick.Layouts
import Quickshell
import qs.Commons
import qs.Ui
import "qml/lib/Panel.js" as Panel
import "qml/views"

// Book glyph that toggles an anchored, themed drawer. The widget is a view
// only: one instance exists per monitor, and all state lives in the service.
BarWidget {
  id: root
  moduleName: "latentoperator.audible"

  readonly property var service: bar && bar.shell
    ? bar.shell.serviceFor("latentoperator.audible") : null
  readonly property var player: service ? service.player : null
  readonly property string barTitle: Panel.barTitle(String(setting("showTitleInBar", "Off")), vertical,
    player ? player.loaded : false, service && service.loadedRow ? service.loadedRow.title : "")

  property bool opened: false
  property bool popoutSwitchClosing: false

  function open() {
    if (service) service.viewForOpen()
    opened = true
  }
  function close() { opened = false }
  function toggle() { opened ? close() : open() }
  function closeForPopoutSwitch() {
    popoutSwitchClosing = true
    close()
    Qt.callLater(function() { root.popoutSwitchClosing = false })
  }
  function press(mouseButton) {
    if (mouseButton === Qt.MiddleButton) {
      if (player && player.loaded) player.toggle()
    } else if (mouseButton === Qt.LeftButton) {
      toggle()
    }
  }

  implicitWidth: barTitle.length > 0 ? titled.implicitWidth : button.implicitWidth
  implicitHeight: barTitle.length > 0 ? titled.implicitHeight : button.implicitHeight

  onServiceChanged: if (service) service.registerSurface(root)
  Component.onCompleted: if (service) service.registerSurface(root)
  Component.onDestruction: if (service) service.unregisterSurface(root)

  BarIconButton {
    id: button
    anchors.fill: parent
    visible: root.barTitle.length === 0
    bar: root.bar
    text: root.service ? root.service.barGlyph : Panel.GLYPH_BOOK
    tooltipText: root.service ? root.service.tooltipText : "Omarchy Audible"
    onPressed: function(b) { root.press(b) }
  }

  // The same button with the title beside the glyph (setting `showTitleInBar`).
  WidgetButton {
    id: titled
    anchors.fill: parent
    visible: root.barTitle.length > 0
    bar: root.bar
    text: button.text + "  " + root.barTitle
    tooltipText: button.tooltipText
    onPressed: function(b) { root.press(b) }
  }

  KeyboardPanel {
    id: popup
    anchorItem: root.barTitle.length > 0 ? titled : button
    bar: root.bar
    owner: root
    open: root.opened
    focusTarget: keys
    contentWidth: fittedContentWidth(Style.space(380))
    contentHeight: fittedContentHeight(views.implicitHeight, Style.space(560))

    PanelKeyCatcher {
      id: keys
      anchors.fill: parent
      onCloseRequested: root.close()

      StackLayout {
        id: views
        width: parent.width
        currentIndex: Panel.viewIndex(root.service ? root.service.view : "")

        OnboardingView { service: root.service }
        LibraryView { service: root.service }
        MiniView { service: root.service }
        FullView { service: root.service }
      }
    }
  }
}
