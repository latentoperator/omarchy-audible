import QtQuick
import "../components"

// Placeholder until U2a: title, author, time and basic controls.
ViewPlaceholder {
  property var service: null

  heading: "Now playing"
  body: service ? service.tooltipText : ""
}
