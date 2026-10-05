import QtQuick

import "lib/Library.js" as Library
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

  property string sortKey: Library.SORT_RECENT
  property string filterKey: Library.FILTER_ALL
  property string searchText: ""

  readonly property var allRows: Library.buildRows(
    Playback.parseJson(catalogText, null),
    Playback.parseJson(remoteText, null),
    stateDoc, localBooks, jobs)

  readonly property var rows: Library.searchRows(
    Library.filterRows(Library.sortRows(allRows, sortKey), filterKey), searchText)
  readonly property int count: rows.length

  function rowFor(asin) {
    for (var i = 0; i < allRows.length; i++) {
      if (allRows[i].asin === asin) return allRows[i]
    }
    return null
  }
}
