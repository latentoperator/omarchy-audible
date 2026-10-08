import QtQuick
import QtQuick.Layouts
import Quickshell
import qs.Commons
import qs.Ui
import "qml/lib/Glyphs.js" as Glyphs
import "qml/lib/Mini.js" as Mini
import "qml/lib/Panel.js" as Panel
import "qml/lib/Player.js" as Player
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
  property bool enterPressed: false

  function open() {
    if (service) service.viewForOpen()
    opened = true
  }
  // KeyboardPanel calls this for every outside click, including the
  // dismissal windows it puts on the other monitors.
  function close() {
    if (service && opened && !Panel.dismissClosesPanel(service.view, service.chapterListOpen)) {
      service.chapterListOpen = false
      return
    }
    opened = false
  }
  function toggle() { opened ? close() : open() }
  // Another popout takes over: always close the whole panel.
  function closeForPopoutSwitch() {
    if (service) service.chapterListOpen = false
    popoutSwitchClosing = true
    close()
    Qt.callLater(function() { root.popoutSwitchClosing = false })
  }
  // Space and ←/→ while Mini (or Full) shows: play/pause and skip.
  function panelKey(kind, dx) {
    if (!service || !player) return
    var action = Mini.keyAction(service.view, player.loaded, kind, dx)
    if (action === Mini.ACTION_TOGGLE) service.playPause()
    else if (action !== Mini.ACTION_NONE) player.skip(Mini.skipSeconds(action))
  }

  // Backspace in Full collapses to Mini.
  function panelText(text) {
    if (service && Player.fullKeyAction(service.view, text) === Player.KEY_COLLAPSE) service.showView(Panel.VIEW_MINI)
  }

  // Library takes keys in its search field; every other view through the
  // catcher. Also runs the sync-on-open check when the Library shows.
  function focusView() {
    if (!opened || !service) return
    if (service.view === Panel.VIEW_LIBRARY) {
      Qt.callLater(function() { if (root.opened) libraryView.focusSearch() })
      service.libraryOpened()
    } else {
      Qt.callLater(function() { if (root.opened) keys.forceActiveFocus() })
    }
  }

  Connections {
    target: root.service
    function onViewChanged() { root.focusView() }
  }

  function press(mouseButton) {
    if (mouseButton === Qt.MiddleButton) {
      if (service && player && player.loaded) service.playPause()
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
    text: root.service ? root.service.barGlyph : Glyphs.GLYPH_BOOK
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
    readonly property string viewName: root.service ? root.service.view : ""
    contentWidth: fittedContentWidth(Style.space(Panel.contentWidth(viewName)))
    // The current view's height, not the tallest view's.
    contentHeight: fittedContentHeight(views.currentHeight, Style.space(Panel.heightCap(viewName)))
    onOpenChanged: if (open) root.focusView()

    PanelKeyCatcher {
      id: keys
      anchors.fill: parent
      // While the Library search field has focus it handles its own keys.
      blocked: libraryView.searchFocused || onboardingView.inputFocused
      onCloseRequested: root.close()
      // The catcher sends Enter as returnRequested then activateRequested,
      // and Space as activateRequested alone.
      onReturnRequested: root.enterPressed = true
      onActivateRequested: {
        root.panelKey(root.enterPressed ? "enter" : "space", 0)
        root.enterPressed = false
      }
      onMoveRequested: function(dx, dy) { if (dy === 0) root.panelKey("move", dx) }
      onTextKey: function(text) { root.panelText(text) }

      StackLayout {
        id: views
        width: parent.width
        currentIndex: Panel.viewIndex(root.service ? root.service.view : "")
        readonly property real currentHeight: {
          var item = children[currentIndex]
          return item ? item.implicitHeight : 0
        }

        OnboardingView {
          id: onboardingView
          service: root.service
          onCloseRequested: root.close()
        }
        LibraryView {
          id: libraryView
          service: root.service
          onCloseRequested: root.close()
        }
        MiniView {
          service: root.service
          panelOpen: root.opened
          onCloseRequested: root.close()
          onKeysReleased: root.focusView()
        }
        FullView {
          service: root.service
          onCloseRequested: root.close()
        }
      }
    }
  }
}
