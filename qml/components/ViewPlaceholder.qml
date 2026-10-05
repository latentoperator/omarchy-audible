import QtQuick
import qs.Commons

// A heading and one line of text, for views that are not built yet.
Column {
  id: root

  property string heading: ""
  property string body: ""

  spacing: Style.spacing.md

  Text {
    width: root.width
    text: root.heading
    elide: Text.ElideRight
    color: Color.popups.text
    font.family: Style.font.family
    font.pixelSize: Style.font.heading
  }

  Text {
    width: root.width
    text: root.body
    wrapMode: Text.WordWrap
    color: Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }
}
