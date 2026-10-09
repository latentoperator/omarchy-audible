import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "../lib/Glyphs.js" as Glyphs
import "../lib/Mini.js" as Mini
import "../lib/Player.js" as Player

// ⏮ ⏪N ⏯ ⏩N ⏭ ■ (FR-U3, FR-P2). ⏯ goes through the service, so a resume
// first checks the account for a newer position on another device.
RowLayout {
  id: root

  property var service: null

  readonly property var player: service ? service.player : null
  readonly property bool loaded: player ? player.loaded : false

  spacing: Style.spacing.xs

  Button {
    enabled: root.loaded && Player.canJumpChapter(root.player.chapterIndex, root.player.chapters.length, -1)
    iconText: Glyphs.GLYPH_PREV_CHAPTER
    tooltipText: "Previous chapter"
    onClicked: root.player.prevChapter()
  }

  Button {
    enabled: root.loaded
    iconText: Glyphs.GLYPH_BACK
    text: root.service ? String(root.service.skipSeconds) : "15"
    tooltipText: "Back " + (root.service ? root.service.skipSeconds : 15) + " s (←)"
    onClicked: root.player.skip(Mini.skipSeconds(Mini.ACTION_BACK, root.service ? root.service.skipSeconds : 15))
  }

  Button {
    enabled: root.loaded
    iconText: Mini.playGlyph(root.player ? root.player.playing : false)
    tooltipText: "Play / pause (Space)"
    onClicked: root.service.playPause()
  }

  Button {
    enabled: root.loaded
    iconText: Glyphs.GLYPH_FORWARD
    text: root.service ? String(root.service.skipSeconds) : "15"
    tooltipText: "Forward " + (root.service ? root.service.skipSeconds : 15) + " s (→)"
    onClicked: root.player.skip(Mini.skipSeconds(Mini.ACTION_FORWARD, root.service ? root.service.skipSeconds : 15))
  }

  Button {
    enabled: root.loaded && Player.canJumpChapter(root.player.chapterIndex, root.player.chapters.length, 1)
    iconText: Glyphs.GLYPH_NEXT_CHAPTER
    tooltipText: "Next chapter"
    onClicked: root.player.nextChapter()
  }

  Button {
    enabled: root.loaded
    iconText: Glyphs.GLYPH_STOP
    tooltipText: "Stop"
    onClicked: root.service.quitPlayer()
  }
}
