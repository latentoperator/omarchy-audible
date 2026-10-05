import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "../components"
import "../lib/Drawer.js" as Drawer
import "../lib/Format.js" as Format
import "../lib/LibraryUi.js" as LibraryUi

// Library view (U2): search, sort, filters, the book list, the storage line
// and Remove all downloads. Every decision comes from `LibraryUi.js` and
// `Drawer.js`; the service does the work.
ColumnLayout {
  id: root

  property var service: null

  readonly property var library: service ? service.library : null
  readonly property var list: service ? service.listState : ({ "state": "loading", "banner": null })
  readonly property bool offline: service ? service.syncFailure.offline : false
  readonly property string loadedAsin: service ? service.loadedAsin : ""
  readonly property var askRow: service && service.askAsin.length > 0 ? library.rowFor(service.askAsin) : null
  readonly property var storage: LibraryUi.storage(library ? library.localBooks : [])
  readonly property var removable: Drawer.removableAsins(library ? library.allRows : [], loadedAsin)
  readonly property bool searchFocused: search.activeFocus
  property int selected: -1
  property bool confirmRemoveAll: false

  signal closeRequested()

  spacing: Style.spacing.md

  function focusSearch() {
    search.forceActiveFocus()
  }

  function move(delta) {
    selected = LibraryUi.moveSelection(selected, delta, library ? library.count : 0)
    if (selected >= 0) books.positionViewAtIndex(selected, ListView.Contain)
  }

  function pickAt(index) {
    if (!service || !library || index < 0 || index >= library.count) return
    selected = index
    service.pick(library.rows[index].asin)
  }

  Connections {
    target: root.library
    function onRowsChanged() {
      if (root.selected >= root.library.count) root.selected = root.library.count - 1
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
        if (action === Drawer.KEY_CLOSE) root.closeRequested()
        else if (action === Drawer.KEY_MOVE_UP) root.move(-1)
        else if (action === Drawer.KEY_MOVE_DOWN) root.move(1)
        else if (action === Drawer.KEY_PICK) root.pickAt(Drawer.pickIndex(root.selected, root.library ? root.library.count : 0))
        else if (action === Drawer.KEY_TOGGLE) { if (root.service && root.service.player.loaded) root.service.player.toggle() }
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
      iconText: Drawer.GLYPH_REFRESH
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

  Text {
    Layout.fillWidth: true
    visible: text.length > 0
    text: Drawer.bannerText(root.list.banner)
    textFormat: Text.PlainText
    wrapMode: Text.WordWrap
    color: root.list.banner === LibraryUi.BANNER_RECONNECT ? Color.urgent : Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
  }

  // A finished book far from its end: resume or start over (SCOPE 6).
  RowLayout {
    Layout.fillWidth: true
    visible: root.askRow !== null
    spacing: Style.spacing.md

    Text {
      Layout.fillWidth: true
      text: root.askRow ? root.askRow.title : ""
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
  }

  Item {
    Layout.fillWidth: true
    implicitHeight: Style.space(340)

    Text {
      anchors.centerIn: parent
      width: parent.width
      visible: root.list.state !== LibraryUi.STATE_LIST
      horizontalAlignment: Text.AlignHCenter
      wrapMode: Text.WordWrap
      text: Drawer.stateText(root.list.state)
      textFormat: Text.PlainText
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.body
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
        removable: Drawer.canRemove(modelData, root.loadedAsin)
        onPicked: root.pickAt(index)
        onRemoveRequested: root.service.removeBook(modelData.asin)
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
}
