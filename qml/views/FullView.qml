import QtQuick
import qs.Commons
import qs.Ui
import "../components"
import "../lib/Panel.js" as Panel

// Placeholder until U6: cover, chapters, speed and sleep timer. Mini's
// maximize button opens it, so it has a way back.
Column {
  id: root

  property var service: null

  spacing: Style.spacing.panelGap

  ViewPlaceholder {
    width: root.width
    heading: "Player"
    body: "The full player arrives in a later milestone."
  }

  Button {
    text: "Back to the mini player"
    bordered: true
    onClicked: if (root.service) root.service.showView(Panel.VIEW_MINI)
  }
}
