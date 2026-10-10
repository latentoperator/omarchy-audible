import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "../lib/Onboarding.js" as Onboarding
import "../lib/Signin.js" as Signin

// Onboarding view (U3): missing tools, setup, and connecting Audible (store,
// sign-in link, paste, or import an existing audible-cli login). Steps come
// from `Onboarding.step` via the service; the pasted text lives only in the
// field and goes straight to `service.finishLogin`.
ColumnLayout {
  id: root

  property var service: null

  readonly property var status: service ? service.status : null
  readonly property string step: service ? service.onboardingStep : Onboarding.STEP_LOADING
  readonly property string phase: service ? service.loginPhase : Signin.PHASE_PICK
  readonly property var error: service ? service.onboardingError : null
  readonly property bool inputFocused: paste.activeFocus

  signal closeRequested()

  spacing: Style.spacing.panelGap

  function send() {
    if (service) service.finishLogin(paste.text)
  }

  Connections {
    target: root.service
    function onClipboardRead(target, chunk) { if (target === root) paste.text += chunk }
    function onClearPaste() { paste.text = "" }
  }

  Text {
    Layout.fillWidth: true
    text: Signin.heading(root.step, root.service ? root.service.reconnecting : false)
    textFormat: Text.PlainText
    wrapMode: Text.WordWrap
    color: Color.popups.text
    font.family: Style.font.family
    font.pixelSize: Style.font.heading
  }

  // --- Missing tools -------------------------------------------------------
  ColumnLayout {
    Layout.fillWidth: true
    visible: root.step === Onboarding.STEP_MISSING
    spacing: Style.spacing.md

    Text {
      Layout.fillWidth: true
      text: "Install them in a terminal, then check again."
      textFormat: Text.PlainText
      wrapMode: Text.WordWrap
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }

    Rectangle {
      Layout.fillWidth: true
      implicitHeight: command.implicitHeight + Style.spacing.lg * 2
      radius: Style.cornerRadius
      color: Style.normalFill

      Text {
        id: command
        anchors.fill: parent
        anchors.margins: Style.spacing.lg
        text: Onboarding.installCommand(root.status ? root.status.missing : [])
        textFormat: Text.PlainText
        wrapMode: Text.WrapAnywhere
        color: Color.popups.text
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }
    }

    RowLayout {
      spacing: Style.spacing.md
      Button {
        text: "Copy command"
        onClicked: root.service.copyText(command.text)
      }
      Button {
        text: "Check again"
        onClicked: root.service.checkStatus()
      }
    }
  }

  // --- Setup ---------------------------------------------------------------
  ColumnLayout {
    Layout.fillWidth: true
    visible: root.step === Onboarding.STEP_SETUP
    spacing: Style.spacing.md

    Text {
      Layout.fillWidth: true
      text: Signin.setupLine(root.service ? root.service.settingUp : false,
        root.service ? root.service.runner.progress : null)
      textFormat: Text.PlainText
      wrapMode: Text.WordWrap
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }

    Button {
      text: "Set up"
      enabled: root.service ? !root.service.settingUp : false
      onClicked: root.service.startSetup()
    }
  }

  // --- Connect -------------------------------------------------------------
  ColumnLayout {
    Layout.fillWidth: true
    visible: root.step === Onboarding.STEP_CONNECT
    spacing: Style.spacing.md

    // Pick a store and start.
    ColumnLayout {
      Layout.fillWidth: true
      visible: root.phase === Signin.PHASE_PICK
      spacing: Style.spacing.md

      Text {
        Layout.fillWidth: true
        text: "Sign in with Amazon in your browser. Captcha, two-step and passkeys all happen there. Amazon then shows a “page not found” page: that's expected. Copy its address and come back here to paste it."
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        color: Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }

      RowLayout {
        Layout.fillWidth: true
        spacing: Style.spacing.md

        Dropdown {
          id: store
          Layout.fillWidth: true
          showLabel: false
          options: Signin.storeOptions(Onboarding.marketplaces())
          value: root.service ? root.service.marketplace : Signin.DEFAULT_MARKETPLACE
          onChanged: function(value) { if (root.service) root.service.marketplace = value }
        }
        Button {
          text: "Connect Audible"
          onClicked: root.service.startLogin(store.value)
        }
      }

      Button {
        text: "Use existing audible-cli login"
        onClicked: root.service.importCliLogin()
      }
    }

    Text {
      Layout.fillWidth: true
      visible: text.length > 0
      text: Signin.phaseText(root.phase)
      textFormat: Text.PlainText
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }

    // Paste the address of the page Amazon lands on.
    ColumnLayout {
      Layout.fillWidth: true
      visible: root.phase === Signin.PHASE_PASTE
      spacing: Style.spacing.md

      Text {
        Layout.fillWidth: true
        text: "After you sign in, the browser shows a “page not found” page. Copy its address and paste it here."
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        color: Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }

      TextField {
        id: paste
        Layout.fillWidth: true
        password: true
        placeholderText: "Page address"
        Keys.onPressed: function(event) {
          var action = Signin.pasteKey(event.key)
          if (action === "close") root.closeRequested()
          else if (action === "send") root.send()
          else return
          event.accepted = true
        }
      }

      Text {
        Layout.fillWidth: true
        visible: root.service ? root.service.pasteRejected : false
        text: Signin.pasteMessage(root.service ? root.service.pasteEmpty : false)
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        color: Color.urgent
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }

      RowLayout {
        spacing: Style.spacing.md
        Button {
          text: "Paste from clipboard"
          onClicked: {
            paste.text = ""
            root.service.readClipboard(root)
          }
        }
        Button {
          text: "Connect"
          onClicked: root.send()
        }
        Button {
          text: "Start over"
          onClicked: root.service.cancelLogin()
        }
      }
    }
  }

  // Errors from setup, sign-in or import.
  ColumnLayout {
    Layout.fillWidth: true
    visible: root.error !== null
    spacing: Style.spacing.xxs

    Text {
      Layout.fillWidth: true
      text: root.error ? root.error.title : ""
      textFormat: Text.PlainText
      wrapMode: Text.WordWrap
      color: Color.urgent
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }
    Text {
      Layout.fillWidth: true
      text: root.error ? root.error.body : ""
      textFormat: Text.PlainText
      wrapMode: Text.WordWrap
      color: Color.muted
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }
  }
}
