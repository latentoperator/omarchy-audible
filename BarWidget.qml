import QtQuick
import Quickshell
import qs.Commons
import qs.Ui

// Book glyph that toggles an anchored, themed drawer. The widget is a view
// only: one instance exists per monitor, and all state lives in the service.
BarWidget {
  id: root
  moduleName: "latentoperator.audible"

  readonly property var service: bar && bar.shell
    ? bar.shell.serviceFor("latentoperator.audible") : null

  property bool opened: false
  property bool popoutSwitchClosing: false

  function open() { opened = true }
  function close() { opened = false }
  function toggle() { opened ? close() : open() }
  function closeForPopoutSwitch() {
    popoutSwitchClosing = true
    close()
    Qt.callLater(function() { root.popoutSwitchClosing = false })
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onServiceChanged: if (service) service.registerSurface(root)
  Component.onCompleted: if (service) service.registerSurface(root)
  Component.onDestruction: if (service) service.unregisterSurface(root)

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: ""
    tooltipText: "Omarchy Audible"
    onPressed: function(b) { root.toggle() }
  }

  KeyboardPanel {
    id: popup
    anchorItem: button
    bar: root.bar
    owner: root
    open: root.opened
    focusTarget: keys
    contentWidth: fittedContentWidth(Style.space(380))
    contentHeight: fittedContentHeight(content.implicitHeight, Style.space(560))

    PanelKeyCatcher {
      id: keys
      anchors.fill: parent
      onCloseRequested: root.close()

      // TEMPORARY (removed in U1): debug panel for the P1 job runner.
      Column {
        id: content
        width: parent.width
        spacing: Style.spacing.md

        Text {
          text: "Omarchy Audible" + (root.service && root.service.fake ? "  ·  FAKE" : "")
          color: root.service && root.service.fake ? Color.accent : Color.popups.text
          font.family: Style.font.family
          font.pixelSize: Style.font.heading
        }

        Text {
          width: parent.width
          wrapMode: Text.WordWrap
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          text: {
            var runner = root.service ? root.service.runner : null
            if (!runner) return "service not loaded"
            var line = "running: " + runner.running + "   queued: " + runner.queued
            if (runner.activeJob) line += "\nactive: " + runner.activeJob.command
            if (runner.progress) line += "\nprogress: " + JSON.stringify(runner.progress)
            if (runner.lastError) line += "\nlast error: " + runner.lastError.code
            return line
          }
        }

        Row {
          spacing: Style.spacing.sm

          Repeater {
            model: [
              { "label": "status", "command": "status" },
              { "label": "sync", "command": "sync" },
              { "label": "get first", "command": "get" }
            ]

            Rectangle {
              required property var modelData
              // Real mode only runs the read-only commands.
              readonly property bool allowed: modelData.command !== "get"
                || (root.service && root.service.fake)
              width: label.implicitWidth + Style.spacing.lg * 2
              height: label.implicitHeight + Style.spacing.md
              radius: Style.cornerRadius
              color: Color.popups.border
              opacity: allowed ? 1 : 0.4

              Text {
                id: label
                anchors.centerIn: parent
                text: parent.modelData.label
                color: Color.popups.text
                font.family: Style.font.family
                font.pixelSize: Style.font.body
              }

              MouseArea {
                anchors.fill: parent
                enabled: parent.allowed
                onClicked: {
                  var service = root.service
                  var command = parent.modelData.command
                  if (command === "get") {
                    var asin = service.firstCatalogAsin()
                    if (asin.length > 0) service.run("get", [asin])
                  } else {
                    service.run(command, [])
                  }
                }
              }
            }
          }
        }

        Text {
          width: parent.width
          wrapMode: Text.WrapAnywhere
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
          text: {
            var entries = root.service ? root.service.recentEvents : []
            var lines = []
            for (var i = Math.max(0, entries.length - 12); i < entries.length; i++)
              lines.push(entries[i].label + "  " + entries[i].text)
            return lines.length > 0 ? lines.join("\n") : "no events yet"
          }
        }
      }
    }
  }
}
