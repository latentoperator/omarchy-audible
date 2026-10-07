import QtQuick
import Qt.labs.folderlistmodel

import "lib/Library.js" as Library
import "lib/Parts.js" as Parts
import "lib/Playback.js" as Playback

// One row per catalog book: catalog + remote positions + `state.json` + the
// local scan + job states, merged by Library.js. Views bind to `rows`.
Item {
  id: root

  visible: false
  width: 0
  height: 0

  // Raw inputs, set by the service.
  property string catalogText: ""
  property string remoteText: ""
  property var localBooks: []
  property var jobs: []
  property var stateDoc: null
  property string coversDir: ""

  property string sortKey: Library.SORT_RECENT
  property string filterKey: Library.FILTER_ALL
  property string searchText: ""

  readonly property var allRows: Library.buildRows(
    Playback.parseJson(catalogText, null),
    Playback.parseJson(remoteText, null),
    stateDoc, localBooks, jobs)

  readonly property bool catalogLoaded: Playback.parseJson(catalogText, null) !== null
  readonly property var rows: Library.queryRows(allRows, sortKey, filterKey, searchText)
  readonly property int count: rows.length

  // `{asin: modified ms}` for each cover file on disk; the listing follows
  // the directory, so covers that `sync` fetches or replaces show up without
  // a reload.
  property var coverAsins: ({})

  // False when the covers dir has a character FolderListModel cannot list
  // (see `Parts.listable`); every cover is then tried, and a missing one logs
  // Qt's warning.
  readonly property bool coversListed: Parts.listable(coversDir)

  function hasCover(asin) {
    return !coversListed || coverAsins[asin] !== undefined
  }

  // Bind a Cover's `version` to this so a replaced file is reloaded.
  function coverVersion(asin) {
    var v = coverAsins[asin]
    return v === undefined ? 0 : v
  }

  // Call after `sync`. A covers dir that did not exist when the listing
  // started (a fresh install) is never watched, so its covers would not show
  // until a restart. An empty listing is pointed at the dir again; a listing
  // with covers is left alone, so nothing on screen flickers.
  function rescanCovers() {
    if (!coversListed || covers.count > 0) return
    covers.folder = ""
    covers.folder = Qt.binding(function() {
      return root.coversListed ? Parts.fileUrl(root.coversDir) : ""
    })
  }

  function rowFor(asin) {
    for (var i = 0; i < allRows.length; i++) {
      if (allRows[i].asin === asin) return allRows[i]
    }
    return null
  }

  FolderListModel {
    id: covers
    folder: root.coversListed ? Parts.fileUrl(root.coversDir) : ""
    nameFilters: ["*.jpg"]
    showDirs: false
    showDotAndDotDot: false
    showHidden: false

    function refresh() {
      var entries = []
      for (var i = 0; i < count; i++) {
        var modified = get(i, "fileModified")
        entries.push({
          "name": String(get(i, "fileName")),
          "modified": modified instanceof Date ? modified.getTime() : 0
        })
      }
      root.coverAsins = Parts.coverSet(entries)
    }

    onStatusChanged: if (status === FolderListModel.Ready) refresh()
    onRowsInserted: refresh()
    onRowsRemoved: refresh()
    onModelReset: refresh()
    onDataChanged: refresh()
  }
}
