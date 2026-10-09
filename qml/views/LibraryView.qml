import QtQuick
import QtQuick.Layouts
import Quickshell
import qs.Commons
import qs.Ui
import "../components"
import "../lib/Drawer.js" as Drawer
import "../lib/Format.js" as Format
import "../lib/Glyphs.js" as Glyphs
import "../lib/LibraryUi.js" as LibraryUi
import "../lib/BooksLocation.js" as BooksLocation
import "../lib/Mini.js" as Mini
import "../lib/Settings.js" as Settings
import "../lib/Onboarding.js" as Onboarding
import "../lib/Panel.js" as Panel
import "../lib/Signin.js" as Signin

// Library view (U2): search, sort, filters, the book list, the storage line
// and Remove all downloads. Every decision comes from `LibraryUi.js` and
// `Drawer.js`; the service does the work.
ColumnLayout {
  id: root

  property var service: null

  readonly property var library: service ? service.library : null
  readonly property var list: service ? service.listState : ({ "state": "loading", "banner": null })
  readonly property bool offline: service ? service.syncFailure.offline : false
  readonly property var askRow: service && service.askAsin.length > 0 ? library.rowFor(service.askAsin) : null
  readonly property var storage: LibraryUi.storage(library ? library.localBooks : [])
  readonly property var removable: Drawer.removableAsins(library ? library.allRows : [])
  readonly property bool loaded: service ? service.player.loaded : false
  readonly property bool searchFocused: search.activeFocus
  property int selected: -1
  property bool confirmRemoveAll: false
  property bool confirmDisconnect: false

  signal closeRequested()

  spacing: Style.spacing.md

  function focusSearch() {
    search.forceActiveFocus()
  }

  function move(delta) {
    selected = LibraryUi.moveSelection(selected, delta, library ? library.count : 0)
    if (selected >= 0) books.positionViewAtIndex(selected, ListView.Contain)
  }

  // The download question for a cloud row. Catalog rows carry no size, so
  // it's an estimate from the runtime; an unknown runtime asks without one.
  function questionText(row) {
    var bytes = LibraryUi.estimatedBytes(row)
    return Drawer.downloadQuestion(bytes > 0 ? Format.bytes(bytes) : "")
  }

  function pickAt(index) {
    if (!service || !library || !Drawer.validIndex(index, library.count)) return
    selected = index
    service.pick(library.rows[index].asin)
  }

  Connections {
    target: root.library
    function onRowsChanged() {
      root.selected = Drawer.clampSelection(root.selected, root.library.count)
    }
  }

  RowLayout {
    Layout.fillWidth: true
    spacing: Style.spacing.md

    TextField {
      id: search
      Layout.fillWidth: true
      Layout.minimumWidth: 0
      placeholderText: "Search"
      onTextChanged: {
        if (root.library) root.library.searchText = text
        root.selected = -1
      }
      Keys.onPressed: function(event) {
        var action = Drawer.searchKey(event.key, search.text)
        // Esc first drops an open download question, then closes.
        if (action === Drawer.KEY_CLOSE) {
          if (root.service && root.service.confirmAsin.length > 0) root.service.cancelConfirm()
          else root.closeRequested()
        }
        else if (action === Drawer.KEY_MOVE_UP) root.move(-1)
        else if (action === Drawer.KEY_MOVE_DOWN) root.move(1)
        else if (action === Drawer.KEY_PICK) root.pickAt(Drawer.pickIndex(root.selected, root.library ? root.library.count : 0))
        else if (action === Drawer.KEY_TOGGLE) { if (root.service && root.service.player.loaded) root.service.playPause() }
        else return
        event.accepted = true
      }
    }

    Dropdown {
      Layout.preferredWidth: Style.space(150)
      Layout.maximumWidth: Style.space(150)
      showLabel: false
      options: Drawer.SORTS
      value: root.library ? root.library.sortKey : "recent"
      onChanged: function(value) {
        if (root.library) root.library.sortKey = value
        root.selected = -1
      }
    }

    PanelActionButton {
      iconText: Glyphs.GLYPH_REFRESH
      tooltipText: "Refresh library"
      enabled: root.service ? !root.service.syncing : false
      onClicked: if (root.service) root.service.refreshLibrary()
    }
  }

  RowLayout {
    Layout.fillWidth: true
    spacing: Style.spacing.sm

    Repeater {
      model: Drawer.FILTERS
      Button {
        required property var modelData
        text: modelData.label
        selected: root.library ? root.library.filterKey === modelData.value : false
        onClicked: {
          if (root.library) root.library.filterKey = modelData.value
          root.selected = -1
        }
      }
    }

  }

  // A pick whose player never started (G3 finding 2). The drawer reopens on
  // Library then, since nothing is loaded for Mini.
  Text {
    Layout.fillWidth: true
    visible: root.service ? root.service.playFailure.length > 0 : false
    text: "Couldn't start playback: " + (root.service ? root.service.playFailure : "")
    textFormat: Text.PlainText
    wrapMode: Text.WordWrap
    color: Color.urgent
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
  }

  RowLayout {
    Layout.fillWidth: true
    visible: banner.text.length > 0
    spacing: Style.spacing.md

    Text {
      id: banner
      Layout.fillWidth: true
      text: Drawer.bannerText(root.list.banner, root.service ? root.service.catalogAgeSeconds : null)
      textFormat: Text.PlainText
      wrapMode: Text.WordWrap
      color: root.list.banner === LibraryUi.BANNER_RECONNECT ? Color.urgent : Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }

    // FR-A4: credentials failed in some job; sign in again.
    Button {
      visible: root.list.banner === LibraryUi.BANNER_RECONNECT
      text: "Reconnect"
      onClicked: root.service.reconnect()
    }
  }

  // After sign-in: the code may still be in the clipboard history.
  RowLayout {
    Layout.fillWidth: true
    visible: notice.text.length > 0
    spacing: Style.spacing.md

    Text {
      id: notice
      Layout.fillWidth: true
      text: root.service ? root.service.clipboardNotice : ""
      textFormat: Text.PlainText
      wrapMode: Text.WordWrap
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }

    PanelActionButton {
      iconText: Glyphs.GLYPH_DISMISS
      tooltipText: "Dismiss"
      onClicked: root.service.clipboardNotice = ""
    }
  }

  RowLayout {
    Layout.fillWidth: true
    visible: BooksLocation.shouldShowOldBooks(root.service ? root.service.status : null,
      root.service ? root.service.settingsReceived : false)
    spacing: Style.spacing.md

    Text {
      id: oldBooksText
      Layout.fillWidth: true
      text: root.service && root.service.status
        ? BooksLocation.oldBooksText(root.service.status.old_books, root.service.status.books_dir, Quickshell.env("HOME")) : ""
      textFormat: Text.PlainText
      wrapMode: Text.WordWrap
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }

    Button {
      text: "Got it"
      onClicked: root.service.acknowledgeBooksLocation()
    }
  }

  RowLayout {
    Layout.fillWidth: true
    visible: BooksLocation.shouldShowProblem(root.service ? root.service.status : null,
      root.service ? root.service.settingsReceived : false)
    spacing: Style.spacing.md

    Text {
      id: problemText
      Layout.fillWidth: true
      text: root.service && root.service.status
        ? BooksLocation.problemText(root.service.status.books_dir_problem, root.service.status.books_dir, Quickshell.env("HOME")) : ""
      textFormat: Text.PlainText
      wrapMode: Text.WordWrap
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }
  }

  // A finished book far from its end: resume or start over (SCOPE 6).
  RowLayout {
    Layout.fillWidth: true
    visible: root.askRow !== null
    spacing: Style.spacing.md

    Text {
      Layout.fillWidth: true
      text: Drawer.askText(root.askRow)
      textFormat: Text.PlainText
      elide: Text.ElideRight
      color: Color.popups.text
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }
    Button {
      text: "Resume"
      onClicked: root.service.answerAsk(true)
    }
    Button {
      text: "Start over"
      onClicked: root.service.answerAsk(false)
    }
    PanelActionButton {
      iconText: Glyphs.GLYPH_DISMISS
      tooltipText: "Dismiss"
      onClicked: root.service.dismissAsk()
    }
  }

  Item {
    Layout.fillWidth: true
    implicitHeight: Style.space(340)

    Text {
      anchors.centerIn: parent
      width: parent.width
      horizontalAlignment: Text.AlignHCenter
      wrapMode: Text.WordWrap
      visible: !(root.list.state === LibraryUi.STATE_ERROR && root.service && root.service.lastSyncCode.length > 0
        && ["network", "auth_failed", "busy", "cancelled"].indexOf(root.service.lastSyncCode) === -1)
      text: Drawer.stateText(root.list.state)
      textFormat: Text.PlainText
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }

    ColumnLayout {
      anchors.centerIn: parent
      width: parent.width
      visible: root.list.state === LibraryUi.STATE_ERROR && root.service && root.service.lastSyncCode.length > 0
        && ["network", "auth_failed", "busy", "cancelled"].indexOf(root.service.lastSyncCode) === -1
      spacing: Style.spacing.sm

      Text {
        Layout.fillWidth: true
        text: "Audible connection problem"
        textFormat: Text.PlainText
        horizontalAlignment: Text.AlignHCenter
        color: Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }
      Text {
        Layout.fillWidth: true
        text: "The library could not be read. Copy the diagnostic to help resolve the problem."
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        color: Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }
      Button {
        text: "Copy diagnostic"
        onClicked: root.service.copyDiagnostic()
      }
    }

    ListView {
      id: books
      anchors.fill: parent
      visible: root.list.state === LibraryUi.STATE_LIST
      clip: true
      spacing: Style.spacing.xxs
      model: root.library ? root.library.rows : []
      currentIndex: root.selected
      boundsBehavior: Flickable.StopAtBounds

      delegate: BookRow {
        required property var modelData
        required property int index
        width: books.width
        row: modelData
        selected: index === root.selected
        progress: root.service ? Drawer.rowProgress(modelData.asin, root.service.runner.activeJob, root.service.runner.progress) : null
        offline: root.offline
        dataDir: root.service ? root.service.dataDir : ""
        coverPresent: root.library ? root.library.hasCover(modelData.asin) : false
        coverVersion: root.library ? root.library.coverVersion(modelData.asin) : 0
        removable: Drawer.canRemove(modelData)
        removing: root.service ? Drawer.removing(modelData.asin, root.service.removeAfterUnload,
          root.service.runner.pendingJobs, root.service.runner.activeJob) : false
        iconGlyph: LibraryUi.rowIcon(modelData, root.offline).glyph
        iconTooltip: LibraryUi.rowIcon(modelData, root.offline).tooltip
        confirming: root.service ? root.service.confirmAsin === modelData.asin : false
        questionText: confirming ? root.questionText(modelData) : ""
        asking: root.service ? root.service.askAsin === modelData.asin : false
        onPicked: root.pickAt(index)
        onRemoveRequested: root.service.removeBook(modelData.asin)
        // The question makes the row taller; keep all of it in view. Only for
        // a question just opened on this row: a row recreated while the user
        // scrolls back to an open question must not move the list. Qt also
        // reports the initial `confirming` binding as a change, so changes
        // count only once the delegate is complete.
        property bool revealQuestion: false
        property bool created: false
        Component.onCompleted: created = true
        onConfirmingChanged: if (created) revealQuestion = confirming || asking
        onAskingChanged: if (created) revealQuestion = confirming || asking
        onHeightChanged: if (revealQuestion && (confirming || asking)) books.positionViewAtIndex(index, ListView.Contain)
        onConfirmRequested: root.service.confirmDownload()
        onCancelRequested: root.service.cancelConfirm()
        onResumeRequested: root.service.answerAsk(true)
        onStartOverRequested: root.service.answerAsk(false)
      }
    }
  }

  RowLayout {
    Layout.fillWidth: true
    spacing: Style.spacing.md

    Text {
      Layout.fillWidth: true
      text: root.confirmRemoveAll ? Drawer.removeAllQuestion(root.removable.length)
        : Format.storageLine(root.storage.count, root.storage.bytes)
      textFormat: Text.PlainText
      elide: Text.ElideRight
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }

    Button {
      visible: !root.confirmRemoveAll && root.removable.length > 0
      text: "Remove all downloads"
      onClicked: root.confirmRemoveAll = true
    }
    Button {
      visible: root.confirmRemoveAll
      text: "Remove"
      foreground: Color.urgent
      onClicked: {
        root.confirmRemoveAll = false
        root.service.removeAll()
      }
    }
    Button {
      visible: root.confirmRemoveAll
      text: "Cancel"
      onClicked: root.confirmRemoveAll = false
    }
  }

  // Account row (FR-A3): who is signed in, and Disconnect (asks first).
  RowLayout {
    Layout.fillWidth: true
    spacing: Style.spacing.md

    Text {
      Layout.fillWidth: true
      text: root.confirmDisconnect ? Signin.DISCONNECT_QUESTION
        : Signin.accountLine(root.service && root.service.status ? root.service.status.account : null,
            Signin.marketplaceLabel(root.service && root.service.status ? root.service.status.marketplace : "",
              Onboarding.marketplaces()))
      textFormat: Text.PlainText
      elide: Text.ElideRight
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }

    Button {
      visible: !root.confirmDisconnect
      text: "Disconnect"
      onClicked: root.confirmDisconnect = true
    }
    Button {
      visible: root.confirmDisconnect
      text: "Disconnect"
      foreground: Color.urgent
      onClicked: {
        root.confirmDisconnect = false
        root.service.disconnect()
      }
    }
    Button {
      visible: root.confirmDisconnect
      text: "Cancel"
      onClicked: root.confirmDisconnect = false
    }
  }

  // Now-playing strip (FR-U2, U7): the loaded book, ⏪ ⏯ ⏩, and a click
  // through to Mini.
  Rectangle {
    Layout.fillWidth: true
    visible: root.loaded
    implicitHeight: strip.implicitHeight + Style.spacing.md * 2
    radius: Style.cornerRadius
    color: stripMouse.containsMouse ? Style.hoverFill : Style.normalFill

    MouseArea {
      id: stripMouse
      anchors.fill: parent
      hoverEnabled: true
      onClicked: if (root.service) root.service.showView(Panel.VIEW_MINI)
    }

    RowLayout {
      id: strip
      anchors.fill: parent
      anchors.leftMargin: Style.spacing.lg
      anchors.rightMargin: Style.spacing.md
      spacing: Style.spacing.md

      Text {
        Layout.fillWidth: true
        text: Mini.title(root.loaded, root.service ? root.service.loadedRow : null)
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: Color.popups.text
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }

      PanelActionButton {
        iconText: Glyphs.GLYPH_BACK
        tooltipText: "Back " + (root.service ? root.service.skipSeconds : Settings.DEFAULTS.skipSeconds) + " s"
        onClicked: if (root.service) root.service.player.skip(Mini.skipSeconds(Mini.ACTION_BACK, root.service.skipSeconds))
      }

      PanelActionButton {
        iconText: Mini.playGlyph(root.service ? root.service.player.playing : false)
        tooltipText: "Play / pause"
        onClicked: if (root.service) root.service.playPause()
      }

      PanelActionButton {
        iconText: Glyphs.GLYPH_FORWARD
        tooltipText: "Forward " + (root.service ? root.service.skipSeconds : Settings.DEFAULTS.skipSeconds) + " s"
        onClicked: if (root.service) root.service.player.skip(Mini.skipSeconds(Mini.ACTION_FORWARD, root.service.skipSeconds))
      }
    }
  }
}
