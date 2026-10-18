import QtQuick
import qs.Commons
import qs.Commons as Commons

// Text one step softer than the popup text: names, narrators and notes
// (H1 F26). The theme's muted colour is too faint for names on most themes
// (G3), so this is the popup text at 75%. The one place that value lives.
Text {
  color: Qt.rgba(Commons.Color.popups.text.r, Commons.Color.popups.text.g, Commons.Color.popups.text.b, 0.75)
}
